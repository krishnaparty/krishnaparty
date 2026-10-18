#!/usr/bin/env python3
"""Generate self-contained SVG cards from public GitHub data. Python stdlib only."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
USER = 'krishnaparty'
BG, PANEL, INK, MUTED, BLUE, MINT = '#0b1120', '#121c30', '#edf2ff', '#9aaac6', '#8baaff', '#5eead4'


def fetch(url):
    headers = {'User-Agent': 'krishnaparty-profile', 'Accept': 'application/vnd.github+json' if 'api.github.com' in url else 'text/html', 'Accept-Language': 'en-US'}
    if urllib.parse.urlsplit(url).hostname == 'api.github.com' and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def pages(url):
    result = []
    for page in range(1, 101):
        sep = '&' if '?' in url else '?'
        batch = json.loads(fetch(f'{url}{sep}per_page=100&page={page}'))
        if not isinstance(batch, list):
            raise ValueError('Expected a GitHub list response')
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError('Pagination limit reached; refusing partial results')


class Calendar(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.tips = {}, {}
        self.tip_id = None
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('data-date') and a.get('id'):
            self.cells[a['id']] = a['data-date']
        if tag == 'tool-tip':
            self.tip_id = a.get('for')
            self.buffer = []

    def handle_data(self, data):
        if self.tip_id:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'tool-tip' and self.tip_id:
            self.tips[self.tip_id] = ''.join(self.buffer).strip()
            self.tip_id = None

    def days(self, today):
        out = {}
        for key, day in self.cells.items():
            if day > today.isoformat():
                continue
            text = self.tips.get(key, '')
            match = re.match(r'(No|[\d,]+) contributions?\b', text)
            if not match:
                raise ValueError(f'Unrecognized calendar tooltip for {day}; keeping old charts')
            out[day] = 0 if match[1] == 'No' else int(match[1].replace(',', ''))
        if not 300 <= len(out) <= 370:
            raise ValueError('Unexpected calendar size; keeping old charts')
        ordered = sorted(out)
        if ordered[-1] != today.isoformat():
            raise ValueError('Calendar is stale; keeping old charts')
        if len(out) != (date.fromisoformat(ordered[-1]) - date.fromisoformat(ordered[0])).days + 1:
            raise ValueError('Calendar has missing days')
        return {day: out[day] for day in ordered}


def streaks(days):
    run = longest = 0
    values = list(days.values())
    for value in values:
        run = run + 1 if value else 0
        longest = max(longest, run)
    # An unfinished day does not break yesterday's streak.
    if values and values[-1] == 0:
        values = values[:-1]
    current = 0
    for value in reversed(values):
        if not value:
            break
        current += 1
    return current, longest


def text(x, y, value, size=16, color=INK, weight=400):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}">{escape(str(value))}</text>'


def rect(x, y, w, h, fill=PANEL, radius=12):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"/>'


def svg(title, height, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}" role="img"><title>{escape(title)}</title><g font-family="DejaVu Sans,Segoe UI,Arial,sans-serif">{rect(0,0,960,height,BG,20)}{body}</g></svg>\n'


def chart(title, subtitle, days, color, stamp):
    values = list(days.values())
    ymax = max(max(values, default=0), 1)
    left, top, width, height = 60, 98, 864, 150
    body = text(32, 37, title, 22, INK, 700) + text(32, 64, subtitle, 12, MUTED)
    for fraction in (0, .5, 1):
        y = top + height * (1 - fraction)
        body += f'<path d="M{left},{y} H924" stroke="#24304a"/>' + text(22, y + 4, f'{ymax*fraction:g}', 11, MUTED)
    points = [(left + i * width / max(len(values)-1, 1), top + height*(1-v/ymax)) for i,v in enumerate(values)]
    coords = ' '.join(f'{x:.1f},{y:.1f}' for x,y in points)
    body += f'<polygon points="{left},{top+height} {coords} 924,{top+height}" fill="{color}" opacity="0.10"/>'
    body += f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>'
    keys = list(days)
    for i in sorted(set([0, len(keys)//2, len(keys)-1])):
        x = left+i*width/max(len(keys)-1,1)
        anchor = 'start' if i == 0 else ('end' if i == len(keys)-1 else 'middle')
        body += f'<text x="{x}" y="274" fill="{MUTED}" font-size="11" text-anchor="{anchor}">{keys[i]}</text>'
    body += text(32, 308, f'{sum(values)} in displayed period  /  Refreshed {stamp}', 12, MUTED)
    return svg(title, 330, body)


def collect(today):
    user = json.loads(fetch(f'https://api.github.com/users/{USER}'))
    repos = pages(f'https://api.github.com/users/{USER}/repos?type=owner')
    parser = Calendar()
    parser.feed(fetch(f'https://github.com/users/{USER}/contributions'))
    days = parser.days(today)
    since = today - timedelta(days=89)
    commits = {str(since + timedelta(days=i)): 0 for i in range(90)}
    seen = set()
    for repo in repos:
        # Original owned repositories only; a course fork should not inflate commits.
        if repo['fork']:
            continue
        url = repo['url'] + '/commits?' + urllib.parse.urlencode({'author':USER, 'since':str(since)+'T00:00:00Z'})
        try:
            records = pages(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:  # Empty Git repository.
                continue
            raise
        for commit in records:
            if commit['sha'] in seen:
                continue
            seen.add(commit['sha'])
            day = commit['commit']['committer']['date'][:10]
            if day in commits:
                commits[day] += 1
    return {'updated':today.isoformat(), 'public_repos':user['public_repos'], 'followers':user['followers'], 'stars':sum(r['stargazers_count'] for r in repos if not r['fork']), 'original_repos':sum(not r['fork'] for r in repos), 'days':days, 'commits':commits}


def render(data):
    days, stamp = data['days'], data['updated']
    current, longest = streaks(days)
    body = text(32, 38, 'GITHUB / AT A GLANCE', 17, MINT, 700) + text(32, 65, f'@{USER}  •  Public data  •  Updated {stamp} UTC', 12, MUTED)
    cards = [('Public repositories',data['public_repos']),('Stars earned',data['stars']),('Followers',data['followers']),('Contributions',sum(days.values()))]
    for i,(label,value) in enumerate(cards):
        x = 32 + i*228
        body += rect(x,90,212,104) + text(x+18,137,value,34,INK,700) + text(x+18,172,label,13,MUTED)
    body += text(32,226,'Repositories include forks; stars exclude forks. Contributions cover the calendar below.',12,MUTED)
    outputs = {'overview.svg':svg('GitHub overview',248,body)}
    body = text(32,38,'CONSISTENCY / CONTRIBUTION STREAK',17,MINT,700)
    for i,(label,value) in enumerate([('Current streak',current),('Longest in shown period',longest),('Active days in shown period',sum(v>0 for v in days.values()))]):
        x = 32 + i*304
        body += rect(x,62,288,110) + text(x+18,110,f'{value} '+('day' if value == 1 else 'days'),30,BLUE,700) + text(x+18,145,label,12,MUTED)
    body += text(32,203,'An unfinished day preserves yesterday’s streak. Window: '+next(iter(days))+' to '+stamp,12,MUTED)
    outputs['streak.svg'] = svg('Contribution streak',225,body)
    body = text(32,38,'A YEAR OF BUILDING',22,INK,700) + text(32,65,f'{sum(days.values())} contributions  /  {next(iter(days))} — {stamp}',13,MUTED)
    first = date.fromisoformat(next(iter(days)))
    start = first-timedelta(days=(first.weekday()+1)%7)
    palette = ['#1d2941','#244b62','#267b85','#36b5ad',MINT]
    maxval = max(days.values(),default=1) or 1
    lastmonth = None
    for ds,value in days.items():
        d = date.fromisoformat(ds)
        column = (d-start).days//7
        row = (d.weekday()+1)%7
        x,y = 48+column*16,105+row*16
        level = 0 if not value else min(4,max(1,round(value/maxval*3)+1))
        body += f'<g><title>{ds}: {value} contributions</title>{rect(x,y,12,12,palette[level],3)}</g>'
        if d.month != lastmonth and row == 0:
            body += text(x,93,d.strftime('%b'),10,MUTED)
            lastmonth = d.month
    body += text(32,244,'Includes qualifying commits, pull requests, issues, and other GitHub contributions.',12,MUTED)
    body += text(32,268,'Less',11,MUTED)
    for i,col in enumerate(palette):body += rect(68+i*18,257,12,12,col,3)
    body += text(165,268,'More',11,MUTED)
    outputs['calendar.svg'] = svg('GitHub contribution calendar',290,body)
    outputs['activity.svg'] = chart('CONTRIBUTION ACTIVITY','Daily contributions across the most recent 90 days; not a commit-only count.',dict(list(days.items())[-90:]),MINT,stamp)
    outputs['commits.svg'] = chart('COMMIT ACTIVITY','Authored commits on default branches of owned, non-fork public repositories; UTC committer dates.',data['commits'],BLUE,stamp)
    for filename,content in outputs.items():
        ET.fromstring(content)
    # No generated file is written until all data fetches and SVG validations succeed.
    assets = ROOT/'assets'
    assets.mkdir(exist_ok=True)
    for filename,content in outputs.items():
        temp = assets/(filename+'.tmp')
        temp.write_text(content,encoding='utf-8')
        temp.replace(assets/filename)
    (assets/'stats.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot',type=Path,help='Render a previously captured snapshot without network requests')
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text()) if args.snapshot else collect(datetime.now(timezone.utc).date())
    render(data)
    print('Generated 5 validated SVG charts for '+USER+'; snapshot '+data['updated'])
