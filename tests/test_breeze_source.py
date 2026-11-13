import struct
import unittest
from app.breeze_cow import CowFormatError
from app.breeze_source import decode_source_blob


def blob(channels=None, markers=(2,), extra=b'test'):
    if channels is None:
        channels = [(2, 1000, 0, (-1200, 0, 800)),
                    (1, 200, 0, (1000, 1001, 1005)),
                    (3, 1000, 0, (-1000, 500, 0))]
    count = len(channels[0][3]) if channels else 0
    tail = b''
    for key, scale, representation, values in channels:
        # Nonzero padding must not become a scale, sample count or float.
        tail += struct.pack('<BBhBB', key, 0x79, scale, representation, 0x40)
        tail += struct.pack('<'+str(count)+('h' if representation == 0 else 'i'), *values)
    tail += struct.pack('<'+str(len(markers))+'h', *markers) + extra
    return struct.pack('<IIhhh', 10, 24+len(tail), len(channels), count, len(markers)) + b'\xaa\xbb' + struct.pack('<I', len(extra)) + b'\0\0\xcc\xdd' + tail


class BreezeSourceTests(unittest.TestCase):
    def test_reads_scaling_irregular_timestamps_markers_and_extra_bytes(self):
        decoded = decode_source_blob(blob())
        self.assertEqual(decoded.markers, (2,))
        self.assertEqual(decoded.extra_data, b'test')
        self.assertEqual(decoded.fvl_points(), [(5., -1.2, -1.), (5.005, 0., .5), (5.025, .8, 0.)])
        relative = decoded.fvl_points(relative_time=True)
        self.assertEqual(relative[0][0], 0.)
        self.assertAlmostEqual(relative[-1][0], .025)
        self.assertEqual(decoded.flow_volume_points(), [(-1.2,-1.),(0.,.5),(.8,0.)])

    def test_int32_storage_and_scale_zero_follow_native_division_rule(self):
        decoded = decode_source_blob(blob([(2, 0, 1, (100000, -90000))], (), b''))
        self.assertEqual(decoded.channel(2), (100000., -90000.))
        with self.assertRaises(CowFormatError):
            decoded.flow_volume_points()  # Unknown units cannot be presented as liters.

    def test_tidal_volume_flow_has_no_invented_time_channel(self):
        decoded = decode_source_blob(blob([(2,1000,0,(0,100)),(3,1000,0,(200,-100))], (), b''))
        self.assertEqual(decoded.flow_volume_points(), [(0., .2),(.1,-.1)])
        with self.assertRaises(CowFormatError):
            decoded.fvl_points()

    def test_empty_blob_and_invalid_lengths_versions_formats_and_indices(self):
        self.assertEqual(decode_source_blob(blob([(2,1000,0,()),(3,1000,0,())], (), b'')).fvl_points(), [])
        good = blob()
        cases = [good[:-1], b'\0'*20, struct.pack('<I',11)+good[4:],
                 blob(markers=(3,)), blob([(2,1000,0,(1,2)),(2,1000,0,(1,2))],(),b'')]
        unsupported = bytearray(good)
        unsupported[28] = 2
        cases.append(bytes(unsupported))
        for raw in cases:
            with self.subTest(length=len(raw)), self.assertRaises(CowFormatError):
                decode_source_blob(raw)
