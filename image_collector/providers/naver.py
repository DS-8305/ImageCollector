from .base import BrowserProvider
from urllib.parse import urlencode


class NaverProvider(BrowserProvider):
    engine = "naver"
    cards_script = """
      const results=[], seen=new Set();
      for(const img of document.querySelectorAll('div.image_tile img,div.photo_tile img,img._image')){
        if(seen.has(img)) continue;
        seen.add(img);
        const card=img.closest('.image_tile,.photo_tile')||img.parentElement;
        const anchor=card.querySelector('a[href]')||img.closest('a');
        results.push({thumbnail:img.getAttribute('data-src')||img.currentSrc||img.src,
          source_url:anchor?.href||'',title:img.alt||img.title||'',source:card.innerText||''});
      }
      if(results.length) return results;
      // Observed on Naver 2026-10-13: result data is available while the grid's JS is loading.
      const items=window.imageSearchTabData?.content?.items;
      return Array.isArray(items) ? items.filter(x=>x.type==='image').map(x=>({
        id:x.imgId,thumbnail:x.thumb||x.thumb332||x.thumb280,
        source_url:x.link,title:x.title||'',source:x.writerTitle||x.source||''
      })) : [];
    """

    def search_url(self, keyword):
        return "https://search.naver.com/search.naver?" + urlencode(
            {"where": "image", "sm": "tab_opt", "sort": "date", "query": keyword})
