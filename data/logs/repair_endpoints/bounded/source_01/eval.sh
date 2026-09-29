#!/bin/bash
set -uxo pipefail
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed
python -m pip install -e . --no-build-isolation
export MPLBACKEND=Agg
: '>>>>> Start Test Output'
pytest -rA lib/mpl_toolkits/tests/test_mplot3d.py
test_status=$?
: '>>>>> End Test Output'
exit $test_status
