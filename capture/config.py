IMAGE_DIR = "output"
TEXT_DIR = "text"

# 브라우저 표시 여부 (False: 화면 표시, True: 백그라운드 실행)
HEADLESS = False

# 사이트별 쿠키 동의 완료 쿠키 (현재 main.py에서 비활성화 상태, 최후의 수단으로 보관 중)
# 클릭 기반 처리(동의 버튼 클릭 / CSS 강제 숨김)로 해결이 안 되는 사이트가 나오면
# 여기에 등록하고 main.py의 "[레이어 3 - 비활성화]" 주석을 해제할 것
# 형식: {'name': '쿠키명', 'value': '값'}
# 사이트 쿠키 이름은 브라우저 개발자도구 → Application → Cookies 에서 확인 가능
#
# 참고: Festo는 OneTrust가 아니라 Didomi를 사용하는 것으로 확인됨 (2026-08-05).
# 벤더를 정확히 모르고 등록하면 이번처럼 아무 효과 없는 값이 될 수 있으니,
# 실제 브라우저 개발자도구에서 쿠키명을 직접 확인한 뒤 등록할 것
SITE_COOKIES = {
    # 예시:
    # "example.com": [
    #     {'name': '쿠키명', 'value': '값'},
    # ],
}

# 제외 (네이버, 쿠팡)
EXCLUDE_DOMAINS = [
    "naver.com",
    "coupang.com",
]

# 입력받은 URL
TARGET_URLS = [
    "https://kr.misumi-ec.com/vona2/detail/223012352594/?KWSearch=%EC%84%B8%EC%8B%A0%EB%B2%84%ED%8C%94%EB%A1%9C&searchFlow=results2products&list=PageSearchResult&searchCategorySpec=00&variantType=20260226_pk1_88AovbkGezIbwEO_001",
    "https://smartstore.naver.com/volare73/products/12747389253?nl-ts-pid=jExkOdqX5mhssgJVAxo-092102&NaPm=ct%3Dms8oduve%7Cci%3DER17de9f0f%2D8cb9%2D11f1%2D8a86%2Df69823daf2b3%7Ctr%3Dpla%7Chk%3D20b1d4801dd917853235bddecb4eaecaaaf5137f%7Cnacn%3D68qCBIBdEIn9",
    "https://www.festo.com/kr/ko/a/34411/",
    "https://www.coupang.com/vp/products/8075426128?itemId=22746725406&vendorItemId=95355334252&src=1032001&spec=10305199&addtag=400&ctag=8075426128&lptag=V95355334252&itime=20260715161400&pageType=PRODUCT&pageValue=8075426128&wPcid=17834763995228266688860&wRef=cr.shopping.naver.com&wTime=20260715161400&redirect=landing&mcid=333a0a849fce496da7d0e8ed976a5370&n_keyword=&n_ad_group=&n_ad=&n_rank=&n_keyword_id=&n_media=&n_campaign_type=&n_query=",
    "https://itempage3.auction.co.kr/DetailView.aspx?itemno=F229961590",
    "https://item.gmarket.co.kr/Item?spm=gmktpc.searchlist.prime.d0_3.52a620df7DSmg0&goodscode=3216642412&buyboxtype=ad&utparam-url=%7B%22x_object_id%22%3A%223216642412%22%2C%22x_object_type%22%3A%22item%22%2C%22query%22%3A%22%EC%9D%B4%ED%95%98%20t%EB%A0%8C%EC%B9%98%22%2C%22pvid%22%3A%22f3deae3ed4ec48b1b6a7afe87c12c284%22%2C%22pvid_sys%22%3A%22gmarket%20server%22%2C%22search_session_id%22%3A%225dc5394f-591b-45ff-926d-b03ad2b75938%22%2C%22origin_price%22%3A%2229650%22%2C%22promotion_price%22%3A%2229360%22%2C%22coupon_price%22%3A%22%22%2C%22ab_buckets%22%3A%22%22%2C%22trafficType%22%3A%22ad%22%7D",
    "https://products.swagelok.com/ko/c/%EC%A0%84%EC%9C%84-%ED%8E%98%EB%9F%B4/p/T-8M3-1",
    "https://mall.industry.siemens.com/mall/en/buildingtechnologiesusa/Catalog/Product?mlfb=500-033260&SiepCountryCode=ZU",
]