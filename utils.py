import json
from typing import Dict

import pandas as pd


def load_hypotheses_outcomes(file_path) -> Dict[str, pd.DataFrame]:
    """
    Loads hypothese outcome file
    """
    with open(file_path, 'r') as f:
        data = json.load(f)

    final_result = {}
    for data_item in data:
        for k, v in data_item.items():
            final_result[k] = pd.DataFrame(v)
    return final_result