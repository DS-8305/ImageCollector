"""Bounded local DOM summaries for Google extraction failures (no cookies or HTML)."""
from urllib.parse import urlsplit, urlunsplit

from .storage import atomic_bytes, atomic_json, utc_now


def save_google_diagnostics(driver, directory, rank, consecutive):
    if directory is None:
        return '진단 저장 폴더가 지정되지 않았습니다.'
    from pathlib import Path
    directory = Path(directory)
    report = {'engine': 'google', 'recorded_at': utc_now(), 'rank': rank,
              'consecutive_missing_originals': consecutive, 'capture_errors': []}
    try:
        address = urlsplit(driver.current_url)
        # Search parameters, account identifiers, cookies and storage are not collected.
        report['page'] = urlunsplit((address.scheme, address.hostname or '', address.path, '', ''))
        report.update(driver.execute_script("""
          return {
            card_count: document.querySelectorAll('div.isv-r,div[data-ri][data-docid],div[jsname="dTDiAc"],div[data-lpage][data-docid]').length,
            image_count: document.images.length,
            visible_images: [...document.images].filter(img=>img.getClientRects().length).slice(0,20).map(img=>{
              let host=''; try {host=new URL(img.currentSrc||img.src).hostname;} catch(e){}
              return {classes:String(img.className).slice(0,200), jsname:img.getAttribute('jsname'),
                width:img.naturalWidth,height:img.naturalHeight,source_host:host};
            })
          };
        """) or {})
    except Exception as exc:
        report['capture_errors'].append(type(exc).__name__)
    try:
        atomic_bytes(directory / 'google-original-missing.png', driver.get_screenshot_as_png())
    except Exception as exc:
        report['capture_errors'].append('screenshot: ' + type(exc).__name__)
    try:
        atomic_json(directory / 'google-original-missing.json', report)
        return str(directory)
    except OSError as exc:
        return f'진단 저장 실패 ({type(exc).__name__}): {directory}'
