import re
text = open('scratch/ugg_main.js', encoding='utf-8', errors='replace').read()
for m in re.finditer(r'value:"world"', text):
    s=max(0,m.start()-1200); print(text[s:m.start()+200].replace('\n',' ')); print('-'*100)
