from urllib.parse import urlencode
from urllib.parse import urlparse, parse_qs
from dataclasses import replace
from selenium.common.exceptions import WebDriverException
from .base import BrowserProvider, http_url


def filter_params(options):
    filters = []
    if options.period:
        filters.append("qdr:" + {"day": "d", "week": "w", "month": "m", "year": "y"}[options.period])
    if options.usage_rights:
        filters.append("sur:" + {"creative-commons": "cl", "commercial": "ol"}[options.usage_rights])
    return ",".join(filters)


class GoogleProvider(BrowserProvider):
    engine = "google"
    cards_script = """
      const cards = [...document.querySelectorAll('div.isv-r,div[data-ri][data-docid],div[jsname="dTDiAc"],div[data-lpage][data-docid]')];
      const seen = new Set(), results = [];
      for(const card of cards){
        const img = card.querySelector('img.Q4LuWd,img.YQ4gaf,img');
        if(!img || seen.has(img)) continue;
        seen.add(img);
        const link=card.querySelector('a[href*="imgres"]');
        results.push({element:card.querySelector('a.wXeWr')||img, id:card.dataset.docid||card.dataset.ri,
          thumbnail:img.getAttribute('data-src')||img.currentSrc||img.src,
          title:img.alt||card.getAttribute('aria-label')||'', source:card.innerText||'',
          source_url:card.dataset.lpage||'', original:card.dataset.ou||card.dataset.iurl||'',
          image_link:link?.href||''});
      }
      return results;
    """
    detail_script = """
      const out=[], seen=new Set();
      const selectors=['img[jsname="kn3ccd"]','img.sFlh5c.iPVvYb',
        'img.sFlh5c.FyHeAf','img.sFlh5c.pT0Scc','img.n3VNCb'];
      for(const selector of selectors) for(const img of document.querySelectorAll(selector)) {
        if(seen.has(img)) continue;
        seen.add(img);
        if(!img.getClientRects().length || img.getAttribute('aria-hidden')==='true') continue;
        const src=[img.getAttribute('src'),img.currentSrc,img.getAttribute('data-src')].find(value=>{
          if(!/^https?:\\/\\//i.test(value||'')) return false;
          // A Google cached thumbnail is not the publisher's original URL.
          return !/^(encrypted-tbn\\d*|tbn\\d*)\\.gstatic\\.com$/i.test(new URL(value).hostname);
        });
        if(!src) continue;
        const panel=img.closest('[jsname="figiqf"],[jsname="CGzTgf"],[role="dialog"]')||img.parentElement;
        const links=[...panel.querySelectorAll('a[href]')];
        const link=links.find(a=>a.target==='_blank'&&!a.href.includes('google.com/'));
        const license=links.find(a=>/license|licence|라이선스/i.test(a.innerText));
        out.push({original:src,source_url:link?.href||'',license_url:license?.href||''});
      }
      return out;
    """

    def search_url(self, keyword):
        params = {"q": keyword, "udm": "2", "hl": "en"}
        if filters := filter_params(self.options):
            params["tbs"] = filters
        return "https://www.google.com/search?" + urlencode(params)

    def details(self):
        return self.browser.driver.execute_script(self.detail_script) or []

    def candidate(self, card, rank):
        result = super().candidate(card, rank)
        if self.options.download_mode == "thumbnail":
            return result
        query = parse_qs(urlparse(card.get("image_link", "")).query)
        original = http_url(card.get("original")) or http_url(query.get("imgurl", [""])[0])
        source = result.source_url or http_url(query.get("imgrefurl", [""])[0])
        if original:
            return replace(result, original_url=original, source_url=source)
        driver = self.browser.driver
        previous = {row.get("original") for row in self.details()}
        try:
            element = card["element"]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'})", element)
            element.click()

            def changed(_driver):
                rows = self.details()
                for row in rows:
                    if row.get("original") not in previous and http_url(row.get("original")):
                        return row
                return False

            detail = self.wait(changed, timeout=5)
            if detail:
                return replace(result, original_url=http_url(detail.get("original")),
                               source_url=http_url(detail.get("source_url")) or source,
                               license_url=http_url(detail.get("license_url")))
            if self.logger:
                self.logger(f"Google candidate {rank}: original image was not exposed before the detail deadline.")
        except WebDriverException:
            self.check_cancelled()
            self.page_state()
        return replace(result, source_url=source)
