"""Apply reviewer/dictionary locator→replacement fixes to a translated chunk.

Usage: python apply_fixes.py <draft.md> <fixes.json> [more.json ...] -o <out.md>
Also strips «存style» / «待核» markers and a trailing "## 编辑备注" section.
Fixes whose locator is missing or not unique are skipped and listed on stdout.
"""
import argparse, json, re, sys


def apply(text, fixes):
    skipped = []
    for f in fixes:
        loc, rep = f.get('locator', ''), f.get('replacement', '')
        n = text.count(loc) if loc else 0
        if n == 1:
            text = text.replace(loc, rep)
        elif loc != rep:
            skipped.append({**f, 'reason': 'not found' if n == 0 else f'found {n} times'})
    return text, skipped


def drop_notes(text):  # the editor's notes quote body text, which would make locators non-unique
    return re.sub(r'\n#+ *编辑备注[\s\S]*$', '\n', text)


CJK = r'[　-〿一-鿿＀-￯“”‘’]'


def clean(text):
    text = drop_notes(text).replace('«存style»', '').replace('«待核»', '')
    text = re.sub(f'(?<={CJK})[ \\t]+(?={CJK})', '', text)  # marker removal leaves stray spaces
    return text.rstrip() + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('draft')
    ap.add_argument('fixes', nargs='*')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')  # Windows consoles default to GBK
    # Drop notes, apply, then strip markers: reviewers often quote «待核» in their locators.
    text = drop_notes(open(a.draft, encoding='utf-8').read())
    skipped = []
    for path in a.fixes:
        text, s = apply(text, json.load(open(path, encoding='utf-8')))
        skipped += [{**x, 'file': path} for x in s]
    open(a.out, 'w', encoding='utf-8', newline='').write(clean(text))
    print(json.dumps({'out': a.out, 'skipped': skipped}, ensure_ascii=False, indent=1))


def _selftest():  # py -3 -c "import apply_fixes; apply_fixes._selftest()"
    t, s = apply('甲乙丙乙', [{'locator': '甲', 'replacement': '丁'}, {'locator': '乙', 'replacement': 'x'},
                            {'locator': '无', 'replacement': 'y'}, {'locator': '丙', 'replacement': '丙'}])
    assert t == '丁乙丙乙' and [x['reason'] for x in s] == ['found 2 times', 'not found'], (t, s)
    assert clean('正文«存style»\n\n## 编辑备注\n- 改了\n') == '正文\n'
    assert clean('错了。«存style» 他的 Truman Capote 名') == '错了。他的 Truman Capote 名\n'
    t, s = apply('甲«待核»乙', [{'locator': '甲«待核»', 'replacement': '丙'}])
    assert t == '丙乙' and not s, (t, s)
    print('selftest ok')
