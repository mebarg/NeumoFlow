"""Study USB lifecycle: one zero, repeated captures, explicit zero and idle drain."""
import struct
import unittest
from unittest.mock import patch

from app import spirometry as sp
from app.cpfs_environment import measurement_environment
from app.cpfs_signal import FlowProcessor, StreamSession
from app.workers import StudySessionWorker


class StudySessionTests(unittest.TestCase):
    def test_two_captures_share_zero_and_history_until_explicit_zero(self):
        worker=StudySessionWorker()
        class Device:
            count=0
            def read(self,*args,**kwargs):
                packet=[]
                for i in range(self.count,self.count+10):
                    low=0 if i%100<50 else 3000
                    packet.append(struct.pack('<BHHB',i%128,32768+low,32768,255))
                self.count+=10
                if self.count>300:
                    raise AssertionError('Test session did not stop')
                return b''.join(packet)
        dev=Device()
        processors=[]
        def initialize(device):
            processor=FlowProcessor(.00001,-.00002)
            processors.append(processor)
            device._cpfs_session=StreamSession(processor)
            return 2000
        captures=[]
        curves=[]
        ready=[]
        def on_ready():
            ready.append(True)
            if len(ready)==1:
                worker.start_capture(measurement_environment())
            else:
                worker.shutdown()
        def on_progress(curve):
            curves.append(curve)
            if len(curve)>=101:
                worker.stop()
        def on_finished(samples,params):
            captures.append(samples)
            if len(captures)==1:
                worker.start_capture(measurement_environment())
            else:
                worker.zero()
        worker.ready.connect(on_ready)
        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        errors=[]
        worker.failed.connect(errors.append)
        with patch.object(sp,'open_device',return_value=dev) as opened, \
                patch.object(sp,'inicializar',side_effect=initialize) as zero, \
                patch.object(sp,'send_bytes') as send, patch.object(sp,'flush'), \
                patch.object(sp.usb.util,'release_interface') as release, \
                patch.object(sp.usb.util,'dispose_resources') as dispose:
            worker.run()
        self.assertEqual(errors,[])
        self.assertEqual(opened.call_count,1)
        self.assertEqual(zero.call_count,2)  # study entry + explicit button, not per capture
        self.assertEqual(len(captures),2)
        self.assertEqual([len(s) for s in captures],[100,100])
        self.assertEqual(processors[0].filters[0].count,220)  # includes drained idle intervals
        for samples in captures:
            self.assertEqual(samples[0][0],0.)
            self.assertEqual(samples[-1][0],.99)
            self.assertEqual(samples[0].signal_metadata['zero_low_V'],.00001)
        self.assertEqual(captures[1][0].sample_index,110)
        self.assertEqual(curves[0][-1][0],.05)
        self.assertTrue(all(v==0. for t,v,f in curves[0]))
        # The first processor advanced continuously across the two captures.
        replay=FlowProcessor(.00001,-.00002)
        expected=[replay.step(0 if i%100<50 else 3000,0) for i in range(220)]
        self.assertEqual([s.base_flow for block in captures for s in block],
                         [expected[s.sample_index] for block in captures for s in block])
        self.assertEqual(send.call_count,2)  # explicit zero + session shutdown only
        release.assert_called_once_with(dev,0)
        dispose.assert_called_once_with(dev)

    def test_idle_samples_are_drained_and_not_included_in_capture(self):
        worker=StudySessionWorker()
        class Device:
            count=0
            def read(self,*args,**kwargs):
                start=self.count
                self.count+=10
                if start==20:
                    worker.start_capture(measurement_environment())
                return b''.join(struct.pack('<BHHB',i%128,32768,32768,255)
                                for i in range(start,start+10))
        dev=Device()
        def initialize(device):
            device._cpfs_session=StreamSession(FlowProcessor())
            return 2000
        captured=[]
        worker.progress.connect(lambda curve: worker.stop())
        def finish(samples,params):
            captured.extend(samples)
            worker.shutdown()
        worker.finished.connect(finish)
        errors=[]
        worker.failed.connect(errors.append)
        with patch.object(sp,'open_device',return_value=dev), \
                patch.object(sp,'inicializar',side_effect=initialize), \
                patch.object(sp,'send_bytes'), patch.object(sp.usb.util,'release_interface'), \
                patch.object(sp.usb.util,'dispose_resources'):
            worker.run()
        self.assertEqual(errors,[])
        self.assertEqual(captured[0].sample_index,30)
        self.assertEqual(captured[0][0],0.)
        self.assertEqual(len(captured),10)


if __name__=='__main__':unittest.main()
