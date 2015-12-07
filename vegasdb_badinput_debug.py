import vegasdb
from lxml import etree

db = vegasdb.VegasDb('vegas.db')
timestamp = db.get_timestamp()

with open('badinput.html', 'r') as f:
    root = etree.parse(f)
    events = root.findall('//event')
    
    for e in events:
        parsed = parseEvent(e)
        if parsed is None:
            continue
        gamenumber = parsed['gamenumber']
        gametime = parsed['gametime']
        home_participant = parsed['home_participant']
        visiting_participant = parsed['visiting_participant']
        spread_h = parsed['spread_h']
        spread_v = parsed['spread_v']
        total = parsed['total']
        print gamenumber, gametime, home_participant, visiting_participant, spread_h, spread_v, total

print timestamp
