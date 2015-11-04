import sqlite3
from lxml import etree
from datetime import datetime
import pytz
import time
import nfldb
import requests
from StringIO import StringIO

class VegasDb(object):
    schema = '''
CREATE TABLE IF NOT EXISTS lastpoll (
    id INTEGER PRIMARY KEY,
    unix_timestamp INTEGER
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    gametime DATETIME,
    home STRING,
    visitor STRING,
    UNIQUE(gametime, home, visitor)
);

CREATE TABLE IF NOT EXISTS lines (
    id INTEGER,
    spread_home REAL,
    spread_visitor REAL,
    total_points REAL,
    timestamp INTEGER,
    PRIMARY KEY(id, timestamp)
);
'''
    
    def __init__(self, filename):
        self.conn = sqlite3.connect(filename)
        c = self.conn.cursor()
        c.executescript(VegasDb.schema)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.conn.close()

    def get_timestamp(self):
        c = self.conn.cursor()
        c.execute('SELECT unix_timestamp FROM lastpoll WHERE id=0')
        ts = c.fetchone()
        return ts[0] if ts is not None else None

    def update_timestamp(self):
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO lastpoll (id, unix_timestamp) VALUES (0, ?)', (int(time.time()), ))
        self.conn.commit()

    def add_line(self, gamenumber, gametime, home, visitor, spread_home, spread_visitor, total_points, timestamp):
        c = self.conn.cursor()
        c.execute("INSERT OR IGNORE INTO games(id, gametime, home, visitor) VALUES (?, strftime('%Y-%m-%d %H:%M', ?), ?, ?)", (int(gamenumber), gametime, home, visitor))
        c.execute('INSERT INTO lines(id, spread_home, spread_visitor, total_points, timestamp) VALUES(?, ?, ?, ?, ?)', (int(gamenumber), spread_home, spread_visitor, total_points, int(timestamp)))
        self.conn.commit()

    def get_line(self, team):
        c = self.conn.cursor()
        c.execute('''
SELECT games.gametime, games.visitor, games.home, lines.spread_visitor, lines.spread_home, lines.total_points, max(lines.timestamp)
FROM games
JOIN lines ON games.id=lines.id
WHERE games.gametime >= strftime('%Y-%m-%d', 'now') AND
        (games.home=:team OR games.visitor=:team);
''',
{ 'team' : team })
        r = c.fetchone()
        if r is None:
            return None
        result = list(r)
        d = datetime.strptime(result[0], '%Y-%m-%d %H:%M')
        d = d.replace(tzinfo=pytz.utc)
        result[0] = d
        return result

    def games_by_spread(self):
        c = self.conn.cursor()
        c.execute('''
SELECT games.gametime, games.visitor, games.home, lines.spread_visitor, lines.spread_home, lines.total_points
FROM games
JOIN lines ON lines.id=games.id
JOIN lastpoll ON lastpoll.unix_timestamp=lines.timestamp
WHERE games.gametime >= strftime('%Y-%m-%d %H:%M', 'now')
ORDER BY ABS(lines.spread_visitor) DESC;
''')
        results = c.fetchall()
        results_d = []
        for result in results:
            r = list(result)
            d = datetime.strptime(r[0], '%Y-%m-%d %H:%M')
            d = d.replace(tzinfo=pytz.utc)
            r[0] = d
            results_d.append(r)
        return results_d

def main():
    db = VegasDb('vegas.db')
    
    while True:
        payload = {'sporttype': 'football', 'sportsubtype': 'NFL'}
        timestamp = db.get_timestamp()
#        if timestamp is not None:
#            payload['last'] = timestamp

        r = requests.get('http://xml.pinnaclesports.com/pinnacleFeed.aspx', params=payload)
        if r.status_code != 200:
            raise 'feed request returned status code %d' % r.status_code
        
        db.update_timestamp()
        timestamp = db.get_timestamp()
        
#        root = etree.parse('pinnacleFeed.rss')
        root = etree.parse(StringIO(r.content))
        events = root.findall('//event')

        for e in events:
            if e.find('participants/participant/contestantnum').text == '999':
                continue
            gametime = e.find('event_datetimeGMT').text
            gamenumber = e.find('gamenumber').text
            home_participant = None
            visiting_participant = None
            for p in e.findall('participants/participant'):
                visiting_home_draw = p.find('visiting_home_draw').text
                participant = p.find('participant_name').text
                if visiting_home_draw == 'Visiting':
                    visiting_participant = participant
                elif visiting_home_draw == 'Home':
                    home_participant = participant
            period = e.find('periods/period[1]')
            if period is None:
                spread_v, spread_h, total = None, None, None
            else:
#                if period.find('period_description').text != 'Game':
#                    with open('badinput.html', 'w') as f:
#                        f.write(r.content)
#                    raise 'Incorrect assumption that Game period will always be first period'
                spread_visiting = period.find('spread/spread_visiting')
                if spread_visiting is not None:
                    spread_v = float(spread_visiting.text)
                else:
                    spread_v = None
                spread_home = period.find('spread/spread_home')
                if spread_home is not None:
                    spread_h = float(spread_home.text)
                else:
                    spread_h = None
                total_points = period.find('total/total_points')
                if total_points is not None:
                    total = float(total_points.text)
                else:
                    total = None
            db.add_line(gamenumber, gametime, home_participant, visiting_participant, spread_h, spread_v, total, timestamp)
            print '%s: Added %s (%+0.1f) @ %s (%+0.1f) %0.1fo/u' % (datetime.now(), visiting_participant, spread_v if spread_v is not None else 0, home_participant, spread_h if spread_h is not None else 0, total if total is not None else 0)

        time.sleep(20 * 60) # 20 minutes

if __name__ == '__main__':
    main()

