import requests, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

prefixes = ['gdp','kkk','kkr','kkf','kss','qpt','qsf','qse','qpa','qsg','qsa','qsm','int','sza','sze','isz','klf','klp','xkk','klg','okt','egs','kor','vil','tur','epi','knk','kkk','kbk','kkw','itf','iez','ftk','sgr','akj']

for prefix in prefixes:
    for n in [1, 2, 3, 4, 5, 10, 20, 30, 40, 50]:
        c = f'{prefix}{n:04d}'
        url = f'https://www.ksh.hu/stadat_files/{prefix}/en/{c}.html'
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                m = re.search(r'<title[^>]*>(.*?)</title>', r.text, re.DOTALL|re.IGNORECASE)
                ttl = m.group(1).strip()[:140] if m else '(no-title)'
                print(f'OK {c}: {ttl}', flush=True)
        except Exception as e:
            pass
