"""Human-labelled recording segments; never infer activity from heart rate."""
import csv
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

ACTIVITIES = {'unmarked': '未标注', 'game': '游戏', 'non_game': '非游戏'}
HEADER = ['timestamp', 'iso_time', 'bpm', 'activity', 'segment_id', 'game',
          'label_source', 'base_bpm', 'params_version']


class Segment:
    def __init__(self, directory, activity, game, params):
        self.started = time.time()
        self.id = uuid.uuid4().hex
        self.path = directory / f'heart-rate-{datetime.now():%Y%m%d-%H%M%S-%f}-{activity}-{self.id[:8]}.csv'
        self.meta_path = self.path.with_suffix('.session.json')
        self.activity, self.game = activity, game
        self.source = 'unknown' if activity == 'unmarked' else 'manual'
        self.samples = 0
        self.ended = None
        self.params = dict(params)
        self.stream = self.path.open('x', newline='', encoding='utf-8-sig')
        try:
            self.writer = csv.writer(self.stream)
            self.writer.writerow(HEADER)
            self.stream.flush()
            self.metadata()
        except Exception:
            self.discard()
            raise

    def metadata(self, reason=None):
        data = {'schema': 1, 'segment_id': self.id, 'file': self.path.name,
                'activity': self.activity, 'game': self.game, 'label_source': self.source,
                'started_at': self.started, 'ended_at': self.ended,
                'end_reason': reason, 'samples': self.samples if self.ended is not None else None,
                'params_at_start': self.params}
        temporary = self.meta_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.meta_path)

    def write(self, now, bpm, base, version):
        self.writer.writerow([f'{now:.3f}', datetime.fromtimestamp(now).isoformat(timespec='milliseconds'),
                              bpm, self.activity, self.id, self.game, self.source,
                              '' if base is None else round(base, 3), version])
        self.stream.flush()
        self.samples += 1

    def finish(self, reason):
        # Write the boundary before closing; failure keeps the old segment usable.
        ended = self.ended
        self.ended = time.time()
        try:
            self.metadata(reason)
        except Exception:
            self.ended = ended
            raise
        self.stream.close()

    def discard(self):
        self.stream.close()
        for path in (self.path, self.meta_path, self.meta_path.with_suffix('.tmp')):
            path.unlink(missing_ok=True)


class ActivityRecorder:
    def __init__(self):
        self.directory = None
        self.segment = None
        self.error = ''

    def status(self):
        segment = self.segment
        return {'available': self.directory is not None, 'active': segment is not None,
                'activity': segment.activity if segment else 'unmarked',
                'game': segment.game if segment else '',
                'segment_id': segment.id if segment else None,
                'started_at': segment.started if segment else None,
                'samples': segment.samples if segment else 0,
                'file': segment.path.name if segment else None, 'error': self.error}

    def start(self, directory, params):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        return self._rotate('unmarked', '', params, 'rotation')

    def _rotate(self, activity, game, params, reason):
        candidate = Segment(self.directory, activity, game, params)
        try:
            if self.segment:
                self.segment.finish(reason)
        except Exception:
            candidate.discard()
            raise
        self.segment = candidate
        self.error = ''
        return candidate.path

    def change(self, activity, game, params, expected):
        if activity not in ACTIVITIES:
            raise ValueError('请选择游戏、非游戏或未标注。')
        if not isinstance(game, str) or len(game) > 80 or any(ord(c) < 32 for c in game):
            raise ValueError('游戏名请使用80字以内的单行文字。')
        if not self.segment:
            raise ValueError('当前未开启CSV记录，请去掉 --no-csv 后重启服务。')
        if expected != self.segment.id:
            raise RuntimeError('记录状态已在另一窗口改变，请确认当前状态后重试。')
        game = game.strip() if activity == 'game' else ''
        if (activity, game) != (self.segment.activity, self.segment.game):
            self._rotate(activity, game, params, 'activity_changed')
        return self.status()

    def write(self, now, bpm, base, version):
        if self.segment:
            try:
                self.segment.write(now, bpm, base, version)
                self.error = ''
            except OSError:
                self.error = '心率记录写入失败，请检查磁盘空间或目录权限。'

    def close(self, reason='service_stopped'):
        if self.segment:
            try:
                self.segment.finish(reason)
            finally:
                self.segment.stream.close()
                self.segment = None


def describe_log(path):
    """Legacy three-column logs have unknown context, never presumed non-game."""
    activity, game = 'unmarked', ''
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        count = 0
        labels, games = set(), set()
        for row in reader:
            count += 1
            labels.add(row.get('activity') or 'unmarked')
            games.add(row.get('game') or '')
        if len(labels) == 1 and next(iter(labels)) in ACTIVITIES:
            activity = next(iter(labels))
        if len(games) == 1:
            game = next(iter(games))
    # A zero-sample segment still has a valid, explicitly marked boundary.
    if count == 0:
        try:
            meta = json.loads(path.with_suffix('.session.json').read_text(encoding='utf-8'))
            if meta.get('activity') in ACTIVITIES:
                activity, game = meta['activity'], str(meta.get('game', ''))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return {'samples': count, 'activity': activity, 'game': game}
