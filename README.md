# Collector Car Intelligence Runner

Public, disclosure-reviewed execution surface for Collector Car Intelligence.

This repository contains data-agnostic code only. It excludes private transaction exports, VIN-linked records, credentials, restricted research notes, and production artifacts.

The runner accepts an authorized CSV snapshot at runtime, validates schema and integrity, writes aggregate JSON only, and fails closed when authorization or data quality checks fail.

Local test: python -m unittest discover -s tests -v
