# ROTOBOT

A plugin for the sopel IRC bot to support fantasy football.

Main feature is that it will poll rotoworld's RSS feed and post news updates to the channel.

Also provides:
* `coinflip`: replies heads or tails
* `gameforecast`: weather forecast for games, needs a forecastio api key (they are free up to a certain number of requests)
* `games_by_spread`: games sorted by vegas spread
* `roto`: roto blurb for player
* `schedule`: 5 games of a team's schedule
* `schedule_week`: the nfl schedule this week
* `see_the_future`: generate a prediction for a player's points this week
* `spread`: show vegas spread for a particular game

Please note: I have expended very little effort in making this code nice. It is ugly and poorly organized.

## Completely Untested Setup Procedure

These instructions come with no guarantees, they are totally untested but should be in the ballpark. Rotobot has been successfully run from an ubuntu 14.04 system.

1. Clone this repo into rotobot folder
2. make a virtualenv and install the required pip packages
```
virtualenv ENV
. ENV/bin/activate
# this list of pip packages hasn't been tested, I'm pretty sure they are the ones needed
pip install sopel lxml feedparser requests beautifulsoup4 nfldb forecastio
```
3. (Optional) Create forecastio_api_key.py and put an api key in there to enable gameforecasts e.g.:
```
forecastio_api_key = "buttslol"
```
4. Go to ~/.willie/modules (might be .sopel now??) and create symlinks to the rotobot source. You might have to start sopel once to get this directory to show up.
```
cd ~/.willie/modules
ln -s ~/rotobot/forecastio_api_key.py .
ln -s ~/rotobot/rotobot.py .
ln -s ~/rotobot/stadiums.py
ln -s ~/rotobot/vegasdb.py
```
5. Start the long running `nfldb-update` process to keep your nfl data up to date (use a separate window in screen or something)
```
nfldb-update --interval 86400
```
6. Start the long running `vegasdb.py` process to keep the vegas line data up to date (use a separate window in screen or something). This script is buggy and crashes sometimes when the source data doesn't behave as expected. It occasionally needs to be restarted manually. It dumps the input that broke it to badinput.html, which you could inspect and test with if you feel motivated to try and fix the problem.
```
cd ~/rotobot
python vegasdb.py
```
7. Modify your willie/sopel config to specify the server and channel to join and add rotobot to the module list
8. Start willie/sopel
