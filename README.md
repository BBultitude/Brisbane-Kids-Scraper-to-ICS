# Brisbane-Kids-Scraper-to-ICS
Scraper to generate ics calendar that can be used for Magic Mirror for events for kids designed around https://brisbanekids.com.au/

Running:
To run put files on your MagicMirror box or whatever is going to host the ics file as a website then setup a crontab job as current user to run the run_scraper.sh once a week. As this has to call a browser and takeover the screen its best to run later at night and also setup a crontab as SU to turn off the screen and back on as needed to save the flickering of many webpages opening.

Installing:
To install you need to have python3 installed and make sure the pre-reqs for some of the virtual environments are installed
sudo apt install -y   libnss3   libatk1.0-0   libatk-bridge2.0-0   libcups2   libxkbcommon0   libxcomposite1   libxdamage1   libxrandr2   libgbm1   libasound2   libpangocairo-1.0-0   libpango-1.0-0   libcairo2   libatspi2.0-0   libgtk-3-0

create the project directory then navigate there and transfer the files to and finaly run
python3 -m venv
source /venv/bin/activate
pip install playwright
playwright install chromium
make sure the file is executable by sudo chmod +x ./run_scraper.sh
