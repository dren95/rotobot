from sopel import web
import sopel.module
import sqlite3
import feedparser
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pytz import reference
import itertools
import random
import nfldb
import time
import forecastio
import re
import vegasdb

class VisitedDb(object):
    schema = '''
CREATE TABLE IF NOT EXISTS visited (
    guid PRIMARY KEY,
    title
    );
CREATE INDEX IF NOT EXISTS visited_idx ON visited (guid);
'''

    def __init__(self, filename):
        self.conn = sqlite3.connect(filename)
        c = self.conn.cursor()
        c.executescript(VisitedDb.schema)
        self.conn.commit()

    def __enter__(self):
        return self
    
    def __exit__(self, type, value, traceback):
        self.conn.close()
    
    def log_visited(self, guid, title):
        c = self.conn.cursor()
        c.execute(
            'INSERT INTO visited VALUES (?, ?)',
            (guid, title)
        )
        self.conn.commit()

    def was_visited(self, guid):
        c = self.conn.cursor()
        c.execute('SELECT * FROM visited WHERE guid=?', (guid, ))
        return c.fetchone() is not None

def chunk_text(excess, max_text_length=400):
    # allow a blank line
    if len(excess) == 0:
        yield excess

    while len(excess) > 0:
        text = excess
        excess = ''
        # Encode to bytes, for proper length calculation
        if isinstance(text, unicode):
            encoded_text = text.encode('utf-8')
        else:
            encoded_text = text
        if len(encoded_text) > max_text_length:
            last_space = encoded_text.rfind(' '.encode('utf-8'), 0, max_text_length)
            if last_space == -1:
                excess = encoded_text[max_text_length:]
                encoded_text = encoded_text[:max_text_length]
            else:
                excess = encoded_text[last_space + 1:]
                encoded_text = encoded_text[:last_space]
        # We'll then send the excess at the end
        # Back to unicode again, so we don't screw things up later.
        text = encoded_text.decode('utf-8')
        yield text

from sopel.tools import Identifier
def say_multiline(bot, message):
    recipient = bot._trigger.sender

    bot.sending.acquire()
    try:
        recipient_id = Identifier(recipient)

        if recipient_id not in bot.stack:
            bot.stack[recipient_id] = []
        elif bot.stack[recipient_id]:
            elapsed = time.time() - bot.stack[recipient_id][-1][0]
            if elapsed < 3:
                penalty = float(max(0, len(message) - 50)) / 70
                wait = 0.7 + penalty
                if elapsed < wait:
                    time.sleep(wait - elapsed)

        to_send = []
        for text in message.splitlines():
            for chunk in chunk_text(text):
                to_send.append(chunk)
        
#        bot.write(('PRIVMSG ', recipient), ',--8<-')
        for text in to_send:
            if bot.stack[recipient_id]:
                elapsed = time.time() - bot.stack[recipient_id][-1][0]

                # Loop detection
                messages = [m[1] for m in bot.stack[recipient_id][-8:]]

                # If what we about to send repeated at least 5 times in the
                # last 2 minutes, replace with '...'
                if messages.count(text) >= 5 and elapsed < 120:
                    text = '...'
                    if messages.count('...') >= 3:
                        # If we said '...' 3 times, discard message
                        return

            if len(text) > 0:
                bot.write(('PRIVMSG', recipient), text)
                bot.stack[recipient_id].append((time.time(), bot.safe(text)))
                bot.stack[recipient_id] = bot.stack[recipient_id][-10:]

#        bot.write(('PRIVMSG ', recipient), ',-->8-')
    except:
        pass
    finally:
        bot.sending.release()

def setup(bot):
    bot.running = True
        
def shutdown(bot):
    bot.running = False
        
@sopel.module.interval(60)
def check_roto(bot):
    if not bot.running:
        return
    
    db = VisitedDb('visited.db')

    d = feedparser.parse('http://www.rotoworld.com/rss/feed.aspx?sport=nfl&ftype=news&count=12&format=rss')
    
    for entry in d.entries:
        if db.was_visited(entry.guid):
            continue

        for channel in bot.channels:
            spoke = False
            retries = 5
            while not spoke and retries > 0:
                try:
                    bot.msg(channel, '%s -- %s' % (entry.title, entry.link))
                    if not bot.running:
                        raise 'failed'
                    print '%s: %s -- %s' % (datetime.now(), entry.title, entry.link)
                    spoke = True
                except Exception as e:
                    print e
                    retries -= 1
                    if retries > 0:
                        print 'retrying...'
                    else:
                        print 'failed'
                        raise
        db.log_visited(entry.guid, entry.title)

r_bing = re.compile(r'<h2><a href="([^"]+)"')

def bing_search(query, lang='en-GB'):
    base = 'http://www.bing.com/search?mkt=%s&q=' % lang
    bytes = web.get(base + query)
    m = r_bing.search(bytes)
#    print m
    if m:
        return m.group(1)
r_duck = re.compile(r'nofollow" class="[^"]+" href="(.*?)">')

def duck_search(query):
    query = query.replace('!', '')
    uri = 'http://duckduckgo.com/html/?q=%s&kl=uk-en' % query
    bytes = web.get(uri)
#    if 'web-result"' in bytes:  # filter out the ads on top of the page
#        bytes = bytes.split('web-result"')[1]
#    m = r_duck.search(bytes)
#    if m:
#        return web.decode(m.group(1))
    urls = [web.decode(x) for x in r_duck.findall(bytes)]
    return urls

def get_player_page(name):
    urls = duck_search('rotoworld %s' % name)
    if name != 'jake butt' and name != 'butt':
        urls = filter(lambda x : 'rotoworld.com' in x and '/nfl/' in x, urls)
    else:
        urls = filter(lambda x : ('rotoworld.com' in x) and (x != 'http://www.rotoworld.com/'), urls)
    if len(urls) == 0:
        return None
    
    r = requests.get(urls[0])
    return r.text

@sopel.module.commands('roto')
@sopel.module.example('.roto arian foster')
def roto(bot, trigger):
    dobutts = random.randint(0,1) == 1
    player_name = trigger.group(2)
    try:
        player_page = get_player_page(player_name)
        if player_page is None:
            return bot.reply(".roto couldn't find player '%s'" % player_name)
        soup = BeautifulSoup(player_page, 'lxml')
        item1 = soup.find_all('div', attrs={'class' : 'playernews'})[0]
        report = item1.div.text
        details = item1.find_all('div')[1].text
        message = [report, '', details]
        if dobutts:
            message = [
                x.replace(
                    'yard', 'butt'
                ).replace(
                    'shot', 'squirt'
                ).replace(
                    'touch', 'butt'
                ).replace(
                    'ball', 'poop'
                ).replace(
                    'block', 'boob'
                ).replace(
                    'rush', 'fart'
                ).replace(
                    'passes', 'squirts'
                ).replace(
                    'pass', 'squirt'
                ).replace(
                    'point', 'dong'
                ).replace(
                    'score', 'cum'
                ).replace(
                    'targets', 'dilz'
                ).replace(
                    'wide open', 'goatse'
                ).replace(
                    'end zone', 'anus'
                ).replace(
                    'defense', 'dental dam'
                ) for x in message
            ]
        say_multiline(bot, '\n'.join(message))
    except:
        bot.reply("ERROR '%s' DOES NOT COMPUTE" % player_name)

possible_futures = list(itertools.chain(*[[i] * (51 - i)**2 for i in xrange(51)]))
@sopel.module.commands('see_the_future')
@sopel.module.example('.see_the_future Mark Sanchez')
def see_the_future(bot, trigger):
    player_name = trigger.group(2)
    try:
        bot.reply('I predict %s will score %d fantasy points' % (player_name, possible_futures[random.randint(0, len(possible_futures) - 1)]))
    except:
        bot.reply('the future is unclear at this time')

def player_search2(db, full_name, team=None, position=None,
                  limit=1, soundex=False):
    from nfldb.db import Tx
    import nfldb.sql as sql
    import nfldb.types as types
    """
    Given a database handle and a player's full name, this function
    searches the database for players with full names *similar* to the
    one given. Similarity is measured by the
    [Levenshtein distance](http://en.wikipedia.org/wiki/Levenshtein_distance),
    or by [Soundex similarity](http://en.wikipedia.org/wiki/Soundex).

    Results are returned as tuples. The first element is the is a
    `nfldb.Player` object and the second element is the Levenshtein
    (or Soundex) distance. When `limit` is `1` (the default), then the
    return value is a tuple.  When `limit` is more than `1`, then the
    return value is a list of tuples.

    If no results are found, then `(None, None)` is returned when
    `limit == 1` or the empty list is returned when `limit > 1`.

    If `team` is not `None`, then only players **currently** on the
    team provided will be returned. Any players with an unknown team
    are therefore omitted.

    If `position` is not `None`, then only players **currently**
    at that position will be returned. Any players with an unknown
    position are therefore omitted.

    In order to use this function, the PostgreSQL `levenshtein`
    function must be available. If running this functions gives
    you an error about "No function matches the given name and
    argument types", then you can install the `levenshtein` function
    into your database by running the SQL query `CREATE EXTENSION
    fuzzystrmatch` as a superuser like `postgres`. For example:

        #!bash
        psql -U postgres -c 'CREATE EXTENSION fuzzystrmatch;' nfldb

    Note that enabled the `fuzzystrmatch` extension also provides
    functions for comparing using Soundex.
    """
    assert isinstance(limit, int) and limit >= 1

    if soundex:
        # Careful, soundex distances are sorted in reverse of Levenshtein
        # distances.
        # Difference yields an integer in [0, 4].
        # A 4 is an exact match.
        fuzzy = 'difference(%s, %%s)'
        q = '''
            SELECT {columns}
            FROM player
            WHERE {where}
            ORDER BY distance DESC LIMIT {limit}
        '''
    else:
        fuzzy = 'levenshtein(LOWER(%s), %%s)'
        q = '''
            SELECT {columns}
            FROM player
            WHERE {where}
            ORDER BY distance ASC LIMIT {limit}
        '''

    full_name = full_name.lower()
    tokens = full_name.split(' ')
    for token in tokens:
        team = nfldb.standard_team(token)
        if team != 'UNK':
            tokens.remove(token)
            full_name = ' '.join(tokens)
            break
        team = None

    def get_results(fuzzy, q, name_type, name):
        fuzzy = fuzzy % name_type
        similar = 'LOWER(%s) LIKE %%s' % name_type
        qteam, qposition = '', ''
        results = []
        with Tx(db) as cursor:
            if team is not None:
                qteam = cursor.mogrify('team = %s', (team,))
            if position is not None:
                qposition = cursor.mogrify('position = %s', (position,))
     
            fuzzy_filled = cursor.mogrify(fuzzy, (name,))
            similar_filled = cursor.mogrify(similar, (name + '%',))
            columns = types.Player._sql_select_fields(types.Player.sql_fields())
            columns.append('%s AS distance' % fuzzy_filled)
            q = q.format(
                columns=', '.join(columns),
                where=sql.ands(
                    similar_filled,
                    fuzzy_filled + ' IS NOT NULL',
                    'team != \'UNK\'',
                    qteam, qposition),
                limit=limit)
            cursor.execute(q)
     
            for row in cursor.fetchall():
                results.append((types.Player.from_row_dict(db, row), row['distance']))
        return results

    if len(full_name.split(' ')) > 1:
        first_name, last_name = full_name.split(' ')[:2]
        results_first = get_results(fuzzy, q, 'first_name', first_name)
        results_last = get_results(fuzzy, q, 'last_name', last_name)
        results_dict = {}
        for player, dist in results_last:
            results_dict[str(player)] = dist
        results_2nd_pass = {}
        for player, dist in results_first:
            if str(player) in results_dict:
                results_2nd_pass[player] = (results_dict[str(player)], dist)
        combined_results = results_2nd_pass.items()
        combined_results = sorted(
            combined_results,
            cmp=lambda x, y : x[1][0] - y[1][0] if x[1][0] - y[1][0] != 0 else x[1][1] - y[1][1]
        )
        results = combined_results
    else:
        results = get_results(fuzzy, q, 'last_name', full_name)
        results.extend(get_results(fuzzy, q, 'first_name', full_name))
        results = sorted(results, cmp=lambda x, y : x[1] - y[1])
        
    if limit == 1:
        if len(results) == 0:
            return (None, None)
        return results[0]
    return results

nfldb.player_search2 = player_search2

db = nfldb.connect()

@sopel.module.commands('schedule')
@sopel.module.example('.schedule Alshon')
@sopel.module.example('.schedule denver')
def schedule(bot, trigger):
    season_type, season_year, current_week = nfldb.current(db)
    if current_week is None:
        bot.reply('not currently in season')
        return
    name = trigger.group(2)
    team = nfldb.standard_team(name)
    p = None
    if team == 'UNK':
        results = nfldb.player_search2(db, name, limit=1000)
        if len(results) == 0:
            bot.reply("No player or team matching that name could be found")
            return
        else:
            p = results[0][0]
            team = p.team
    weeks = range(18)
    q = nfldb.Query(db).game(
        season_type=season_type,
        season_year=season_year,
        week=weeks[current_week:current_week+5],
        team=team
    )
    message = []
    if p is not None:
        message.append('Upcoming schedule for %s' % p)
    else:
        message.append('Upcoming schedule for %s' % team)
    for g in q.sort(('week', 'asc')).as_games():
        message.append(str(g))
    say_multiline(bot, '\n'.join(message))

@sopel.module.commands('schedule_week')
@sopel.module.example('.schedule_week')
@sopel.module.example('.schedule_week 12')
def schedule_week(bot, trigger):
    week = None
    if trigger.group(2) is not None:
        try:
            week = int(trigger.group(2))
        except:
            bot.reply('not a valid week')
            return
    season_type, season_year, current_week = nfldb.current(db)
    if season_year is None:
        bot.say('not currently in season')
        return
    if week is None:
        week = current_week
    q = nfldb.Query(db).game(
        season_type='Regular',
        season_year=season_year,
        week=week
    )
    message = [str(g) for g in q.sort(('start_time', 'asc')).as_games()]
    say_multiline(bot, '\n'.join(message))

from stadiums import stadiums
from forecastio_api_key import forecastio_api_key
def windbearing(bearing):
    if 0 <= bearing < 22.5 or 337.5 <= bearing <= 360:
        return 'N'
    elif 22.5 <= bearing < 67.5:
        return 'NE'
    elif 67.5 <= bearing < 112.5:
        return 'E'
    elif 112.5 <= bearing < 157.5:
        return 'SE'
    elif 157.5 <= bearing < 202.5:
        return 'S'
    elif 202.5 <= bearing < 247.5:
        return 'SW'
    elif 247.5 <= bearing < 292.5:
        return 'W'
    elif 292.5 <= bearing < 337.5:
        return 'NW'

@sopel.module.commands('gameforecast')
@sopel.module.example('.gameforecast denver')
def gameforecast(bot, trigger):
    """.gameforecast denver gives the forecast for the denver game this week"""
    week = None
    team = nfldb.standard_team(trigger.group(2))
    if team == 'UNK':
        bot.reply('I do not know that team')
        return

    season_type, season_year, current_week = nfldb.current(db)
    if week is None:
        if current_week is None:
            bot.reply('Not currently in season')
            return
        week = current_week
    
    q = nfldb.Query(db).game(
        season_type='Regular',
        season_year=season_year,
        week=week,
        team=team
    )
    games = q.as_games()
    if len(games) == 0:
        bot.reply('%s is on BYE' % team)
        return
    
    g = games[0]
    start_time = g.start_time
    stadium = stadiums[g.home_team]
    lat, lon = stadium[2]
    output = []
    output.append('Kickoff forecast for %s at %s %s' % (
        g.away_team,
        g.home_team,
        g.start_time.strftime('%Y-%m-%d %I:%M:%S%p')
    ))
    if stadium[3] == False:
        try:
            forecast = forecastio.load_forecast(
                forecastio_api_key,
                lat, lon,
                time=start_time,
                units='us'
            )
            output.append(u'%s %s\u00B0F windspeed %smph from the %s chance of precip %s%%' % (
                forecast.currently().d['summary'],
                forecast.currently().d['temperature'],
                forecast.currently().d['windSpeed'],
                windbearing(forecast.currently().d['windBearing']),
                forecast.currently().d['precipProbability']
            ))
        except:
            output.append('there was an error getting the forecast')
    else:
        output.append('Dome')

    say_multiline(bot, '\n'.join(output))

@sopel.module.rule(r'^butts')
def butts(bot, trigger):
    bot.say(re.sub(r'butts', 'dongs', trigger.group(0)))

@sopel.module.rule(r'^dongs')
def dongs(bot, trigger):
    bot.say(re.sub(r'dongs', 'butts', trigger.group(0)))

headsortails = ['heads', 'tails']
@sopel.module.commands('coinflip')
@sopel.module.example('.coinflip')
def coinflip(bot, trigger):
    try:
        bot.reply(headsortails[random.randint(0, 1)])
    except:
        bot.reply('coin landed on its side')

def format_team(team):
    t = nfldb.Team(db, team)
    return ' '.join([t.city, t.name])

@sopel.module.commands('spread')
@sopel.module.example('.spread eagles')
def spread(bot, trigger):
    vdb = vegasdb.VegasDb('vegas.db')
    team = nfldb.standard_team(trigger.group(2))
    if team == 'UNK':
        bot.reply("No team matching that name could be found")
        return
    line = vdb.get_line(format_team(team))
    if line is None:
        bot.say('sorry i do not have a line for that game at this time')
    ltz = reference.LocalTimezone()
    d = line[0].astimezone(ltz)
    if line[3] is None and line[4] is None and line[5] is None:
        bot.say('sorry i do not have a line for that game at this time')
        return
    message = '%s (%0.1f) @ %s (%0.1f) %0.1fo/u %s' % (
        line[1], line[3] if line[3] is not None else 0,
        line[2], line[4] if line[4] is not None else 0,
        line[5] if line[5] is not None else 0,
        d.strftime('%I:%M%p %A %b %d, %Y')
    )
    bot.say(message)

@sopel.module.commands('games_by_spread')
@sopel.module.example('.games_by_spread')
def games_by_spread(bot, trigger):
    vdb = vegasdb.VegasDb('vegas.db')
    lines = vdb.games_by_spread()
    ltz = reference.LocalTimezone()
    output = []
    for line in lines:
        d = line[0].astimezone(ltz)
        if line[3] is None and line[4] is None and line[5] is None:
            continue
        message = '%s (%0.1f) @ %s (%0.1f) %0.1fo/u %s' % (
            line[1], line[3] if line[3] is not None else 0,
            line[2], line[4] if line[4] is not None else 0,
            line[5] if line[5] is not None else 0,
            d.strftime('%I:%M%p %A %b %d, %Y')
        )
        output.append(message)
    say_multiline(bot, '\n'.join(output))
