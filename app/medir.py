#!/usr/bin/env python3
"""CLI de medición y calibración incluido dentro del paquete de la aplicación."""

from app.spirometry import *  # noqa: F401,F403
from app.spirometry import main


if __name__ == "__main__":
    main()
