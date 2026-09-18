import pandas as pd
for cod in [4536, 4537]:
    try:
        d = pd.read_json(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados/ultimos/3?formato=json")
        print(f"SGS {cod}: OK"); print(d.to_string(index=False)); print()
    except Exception as e:
        print(f"SGS {cod}: ERRO {e}\n")