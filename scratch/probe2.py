import sys, json
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
import importlib
mod = importlib.import_module('app.services.live_recommendation_service')
cls = next(getattr(mod, n) for n in dir(mod)
           if isinstance(getattr(mod, n), type) and 'Recommendation' in n)
e = cls(json.load(open('d:/Accesos/Desktop/Solralol/data/items.json', encoding='utf-8')))
print('recipe 3033:', e._recipe('3033', ['3123']))
print('next 3033:', e._next_buy('3033', ['3123'], 500))
print('from 3033:', e.catalog.get('3033', {}).get('from'))
print('from 3123:', e.catalog.get('3123', {}).get('from'))
print('costs 3033/3123/3035/1018:', [e.cost(i) for i in ('3033', '3123', '3035', '1018')])
print('missing direct  ["3123"]:', e._missing_parts('3033', ['3123']))
print('missing none    []      :', e._missing_parts('3033', []))
print('purchases 3123+1001:', json.dumps(e._purchases(['3123', '1001'], '11'), ensure_ascii=False)[:400])
print('next_buy g=500:', e._next_buy('3123', [], 500))
print('next_buy g=0  :', e._next_buy('3123', [], 0))
print('next_buy rich :', e._next_buy('3123', ['1036'], 10**6))

from scratch.test_live_recommendations import PanelTests, fixture
from PySide6.QtWidgets import QWidget, QLabel
PanelTests.setUpClass()
t = PanelTests()
t.setUp()
t.panel.update_recommendations(fixture())
t.render(1160)
for card in t.panel.left.findChildren(QWidget):
    if card.objectName().startswith('synergyItem_'):
        print(card.objectName(), card.size())
        for label in card.findChildren(QLabel):
            print(label.text(), label.size())
t.tearDown()

