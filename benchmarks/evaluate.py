#!/usr/bin/env python3
"""Compare a manually corrected reference with local/cloud transcript.json files.

python benchmarks/evaluate.py reference.txt local/transcript.json cloud/transcript.json
Reports word and character error rates; no network calls or audio uploads.
"""
import argparse
import json
from pathlib import Path
import re
import unicodedata


def normalize(text):
    text=unicodedata.normalize('NFC',text).casefold()
    return re.sub(r'[^\w\s]', '', text, flags=re.UNICODE)


def distance(a,b):
    row=list(range(len(b)+1))
    for i,left in enumerate(a,1):
        previous=row;row=[i]
        for j,right in enumerate(b,1):
            row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
    return row[-1]


def score(reference,hypothesis):
    ref=normalize(reference);hyp=normalize(hypothesis)
    words=ref.split();chars=''.join(ref.split())
    if not words:raise ValueError('Reference must contain words')
    return dict(word_error_rate=distance(words,hyp.split())/len(words),
                character_error_rate=distance(chars,''.join(hyp.split()))/len(chars),
                reference_words=len(words))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference',type=Path)
    parser.add_argument('transcripts',type=Path,nargs='+')
    args=parser.parse_args()
    for path in args.transcripts:
        data=json.loads(path.read_text())
        result=score(args.reference.read_text(),' '.join(s['text'] for s in data))
        print(json.dumps(dict(file=str(path),**result),ensure_ascii=False))

if __name__=='__main__':main()
