#!/usr/bin/env python3
from collections import defaultdict
import json
import os
import re
import yaml
import argparse
import dateutil
import feedparser
import random
import time
import requests

from bs4 import BeautifulSoup
from mastodon import Mastodon
from datetime import datetime, timezone, MINYEAR

DEFAULT_CONFIG_FILE = os.path.join("~", ".feediverse")
DEFAULT_STATE_FILE = os.path.join("~", ".feediverse_state")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help=("perform a trial run with no changes made: "
                              "don't toot, don't save state"))
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="be verbose")
    parser.add_argument("-c", "--config",
                        help="config file to use",
                        default=os.path.expanduser(DEFAULT_CONFIG_FILE))
    parser.add_argument("-s", "--state",
                        help="file to use to track state",
                        default=os.path.expanduser(DEFAULT_STATE_FILE))
    parser.add_argument("-d", "--delay", action="store_true",
                        help="delay randomly from 10 to 30 seconds between each post")
    parser.add_argument("-p", "--dedupe",
                        help="dedupe against the given tag",
                        default="", metavar="TAG")

    args = parser.parse_args()
    config_file = args.config
    state_file = args.state
    dedupe_field = args.dedupe

    if args.verbose:
        print("using config file", config_file)
        print("using state file", state_file)

    if not os.path.isfile(config_file):
        setup(config_file, state_file)

    config = read_config(config_file)
    state = read_state(state_file)

    masto = Mastodon(
        api_base_url=config['url'],
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        access_token=config['access_token']
    )

    for feed in config['feeds']:
        newest_post = state['updated'][feed["url"]]
        dupes = state['dupecheck'][feed["url"]]
        if args.verbose:
            print(f"fetching {feed['url']} entries since {newest_post}")
        for entry in get_feed(feed['url'], newest_post):
            newest_post = max(newest_post, entry['updated'])
            entry_text = feed['template'].format(**entry)[:499]

            if args.dry_run:
                print(entry_text)
                continue

            if args.verbose:
                print(entry_text)

            if dedupe_field:
                if entry[dedupe_field] in dupes:
                    if args.verbose:
                        print(f"Skipping dupe post: {entry_text} based on dedupe field {dedupe_field}")
                    continue
                update_dupes(dupes, entry[dedupe_field])

            image_medias = []
            if feed.get('include_images', False) and entry['images']:
                for image in entry['images'][:4]:
                    # TODO: handle image fetch and upload exceptions
                    image_response = requests.get(image)
                    image_medias.append(masto.media_post(image_response.content, mime_type=image_response.headers['Content-Type']))

            if not args.dry_run:
                masto.status_post(
                    entry_text,
                    media_ids=image_medias
                )

            if args.delay:
                delay = random.randrange(10,30)
                print("Delaying..." + str(delay) + " seconds...")
                time.sleep(delay)

        if not args.dry_run:
            state['updated'][feed["url"]] = newest_post
            state['dupecheck'] = dupes
            save_state(state, state_file)

def get_feed(feed_url, last_update):
    feed = feedparser.parse(feed_url)
    # RSS feeds can contain future dates that we don't want to post yet,
    # so we filter them out
    now = datetime.now(timezone.utc)
    entries = [e for e in feed.entries
               if dateutil.parser.parse(e['updated']) <= now]
    # Now we can filter for date normally
    if last_update:
        entries = [e for e in entries
                   if dateutil.parser.parse(e['updated']) > last_update]

    entries.sort(key=lambda e: e.updated_parsed)
    for entry in entries:
        yield get_entry(entry)

def update_dupes(dupes, new):
   if len(dupes) > 50:
     del dupes[0]
   dupes.append(new)

def get_entry(entry):
    hashtags = []
    for tag in entry.get('tags', []):
        t = tag['term'].replace(' ', '_').replace('.', '').replace('-', '')
        hashtags.append('#{}'.format(t))
    summary = entry.get('summary', '')
    content = entry.get('content', '')
    comments = entry.get('comments', '')
    if content:
        content = cleanup(content[0].get('value', ''))
    url = entry.id
    return {
        'url': url,
        'link': entry.link,
        'links': entry.links,
        'comments': comments,
        'title': cleanup(entry.title),
        'summary': cleanup(summary),
        'content': content,
        'hashtags': ' '.join(hashtags),
        'images': find_images(summary),
        'updated': dateutil.parser.parse(entry['updated'])
    }

def cleanup(text):
    html = BeautifulSoup(text, 'html.parser')
    text = html.get_text()
    text = re.sub('\xa0+', ' ', text)
    text = re.sub('  +', ' ', text)
    text = re.sub(' +\n', '\n', text)
    text = re.sub('\n\n\n+', '\n\n', text, flags=re.M)
    return text.strip()

def find_urls(html):
    if not html:
        return
    urls = []
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(["a", "img"]):
        if tag.name == "a":
            url = tag.get("href")
        elif tag.name == "img":
            url = tag.get("src")
        if url and url not in urls:
            urls.append(url)
    return urls

def find_images(html):
    if not html:
        return
    urls = []
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(["img"]):
        if tag.name == "img":
            url = tag.get("src")
        if url and url not in urls:
            urls.append(url)
    return urls

def yes_no(question):
    res = input(question + ' [y/n] ')
    return res.lower() in "y1"

def save_config(config, config_file):
    copy = dict(config)
    with open(config_file, 'w') as fh:
        fh.write(yaml.dump(copy, default_flow_style=False))

def read_config(config_file):
    with open(config_file) as fh:
        return yaml.load(fh, yaml.SafeLoader)

def save_state(state, state_file):
    copy = dict(state)
    copy["updated"] = {k: v.isoformat() for k, v in state["updated"].items()}
    with open(state_file, 'w') as fh:
        json.dump(copy, fh, indent=2)

def read_state(state_file):
    state = {
        "updated": defaultdict(lambda: datetime(MINYEAR, 1, 1, 0, 0, 0, 0, timezone.utc)),
        "dupecheck": defaultdict(list),
    }
    try:
        with open(state_file) as fh:
            st = json.load(fh)
            if "updated" in st:
                st["updated"] = {k: dateutil.parser.parse(v) for k, v in st["updated"].items()}
                state["updated"].update(st["updated"])
            if "dupecheck" in st:
                state["dupecheck"].update(st["dupecheck"])
    except FileNotFoundError:
        pass
    return state

def setup(config_file, state_file):
    url = input('What is your Mastodon Instance URL? ')
    have_app = yes_no('Do you have your app credentials already?')
    if have_app:
        name = 'feediverse'
        client_id = input('What is your app\'s client id: ')
        client_secret = input('What is your client secret: ')
        access_token = input('access_token: ')
    else:
        print("Ok, I'll need a few things in order to get your access token")
        name = input('app name (e.g. feediverse): ')
        client_id, client_secret = Mastodon.create_app(
            api_base_url=url,
            client_name=name,
            #scopes=['read', 'write'],
            website='https://github.com/edsu/feediverse'
        )
        username = input('mastodon username (email): ')
        password = input('mastodon password (not stored): ')
        m = Mastodon(client_id=client_id, client_secret=client_secret, api_base_url=url)
        access_token = m.log_in(username, password)

    feed_url = input('RSS/Atom feed URL to watch: ')
    old_posts = yes_no('Shall already existing entries be tooted, too?')
    include_images = yes_no('Do you want to attach images (the first 4) found in entries to your toot?')
    config = {
        'name': name,
        'url': url,
        'client_id': client_id,
        'client_secret': client_secret,
        'access_token': access_token,
        'feeds': [
            {'url': feed_url, 'template': '{title} {url}', 'include_images': include_images}
        ]
    }
    state = read_state(state_file)
    if not old_posts:
        state['updated'][feed_url] = datetime.now(tz=timezone.utc).isoformat()
    save_config(config, config_file)
    save_state(state, state_file)
    print("")
    print("Your feediverse configuration has been saved to {}".format(config_file))
    print("Add a line line this to your crontab to check every 15 minutes:")
    print("*/15 * * * * /usr/local/bin/feediverse")
    print("")

if __name__ == "__main__":
    main()
