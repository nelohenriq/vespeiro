import scrapy


class PublicoArticleItem(scrapy.Item):
    """Scraped article from Público."""
    url = scrapy.Field()
    title = scrapy.Field()
    content_text = scrapy.Field()
    summary = scrapy.Field()
    author = scrapy.Field()
    published_at = scrapy.Field()
