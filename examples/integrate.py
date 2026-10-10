"""Small deterministic CPU example: trapezoidal integral of x squared on [0, 1]."""

import json
import math
import os
from pathlib import Path


def integrate(intervals):
    if type(intervals) is not int or not 1 <= intervals <= 100000:
        raise ValueError('intervals must be an integer from 1 to 100000')
    step = 1 / intervals
    estimate = step * math.fsum([0.5, *((i * step) ** 2 for i in range(1, intervals))])
    return {'intervals': intervals, 'estimate': estimate, 'reference': 1 / 3,
            'absolute_error': abs(estimate - 1 / 3),
            'method': 'composite trapezoidal rule', 'domain': [0, 1],
            'function': 'x squared', 'reference_basis': 'analytic integral'}


def main():
    config = json.loads(Path(os.environ['RESEARCHLEDGER_CONFIG']).read_text())
    # Capture the requested input even if validation rejects it.
    Path('request.json').write_text(json.dumps(config, sort_keys=True) + '\n')
    result = integrate(config['intervals'])
    Path('metrics.json').write_text(json.dumps(result, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
