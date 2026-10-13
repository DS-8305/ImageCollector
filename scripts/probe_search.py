"""Disposable, small live Selenium probe (no image downloads).

Run from the project root: python scripts/probe_search.py --engine google
"""
import argparse
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_collector.browser import BrowserSession
from selenium.webdriver.support.ui import WebDriverWait


def redact_capture(html):
    html = re.sub(r"IP address: [^<\n]+", "IP address: [redacted]", html)
    html = re.sub(r'data-s="[^"]*"', 'data-s="[redacted]"', html)
    html = re.sub(r'(<input[^>]*type="hidden"[^>]*value=")[^"]*(")', r'\1[redacted]\2', html)
    html = re.sub(r'(<iframe[^>]*src=")[^"]*(")', r'\1about:blank\2', html)
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["google", "naver"], default="google")
    parser.add_argument("--keyword", default="red apple")
    parser.add_argument("--output-dir", default=".live-output/probes")
    args = parser.parse_args()
    from urllib.parse import urlencode
    url = ("https://www.google.com/search?" + urlencode({"q": args.keyword, "udm": "2", "hl": "en"})
           if args.engine == "google" else "https://search.naver.com/search.naver?" + urlencode(
               {"where": "image", "sort": "date", "query": args.keyword}))
    browser = BrowserSession(headless=True)
    try:
        driver = browser.driver
        driver.get(url)
        WebDriverWait(driver, 15).until(lambda d: d.execute_script("return document.readyState") == "complete")
        WebDriverWait(driver, 15).until(lambda d: d.execute_script("""
            return !!document.querySelector('#captcha-form,form[action*="consent.google"],div.isv-r,div[data-ri][data-docid]')
              || !!window.imageSearchTabData?.content?.items?.length
              || /did not match any documents|검색결과가 없습니다/.test(document.body.innerText);
        """))
        sample = driver.execute_script("""
            return {url: location.href, title: document.title,
              text: document.body.innerText.slice(0,2500),
              naverInitialCount:window.imageSearchTabData?.content?.items?.length||0,
              images: [...document.images].slice(0,8).map(i=>i.outerHTML),
              ancestors: [...document.images].filter(i=>i.width>80).slice(0,5)
                 .map(i=>i.parentElement.parentElement.outerHTML.slice(0,16000)),
              selectorCounts: Object.fromEntries(['div[data-ri]','div[data-docid]',
                 'div[data-lpage]','div[jsname="dTDiAc"]','a.wXeWr','div.isv-r',
                 'img._image','div.image_tile'].map(s=>[s,document.querySelectorAll(s).length]))};
        """)
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"provider_{args.engine}_live.html").write_text(redact_capture(driver.page_source), encoding="utf-8")
        sample["text"] = re.sub(r"IP address: [^\n]+", "IP address: [redacted]", sample["text"])
        if "/sorry/" in sample["url"]:
            sample["url"] = "https://www.google.com/sorry/index?[redacted]"
            sample["status"] = "needs_attention"
        else:
            sample["status"] = "observed"
        print(json.dumps(sample, ensure_ascii=True, indent=2))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=True))
        return 1
    finally:
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
