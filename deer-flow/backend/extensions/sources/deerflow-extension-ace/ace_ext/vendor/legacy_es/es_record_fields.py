"""Opt-in raw evidence fields for the public document query node."""
import re
from .gsdata_es import EsNewsService


class EvidenceFieldsNewsService(EsNewsService):
    def __init__(self, client, fields):
        super().__init__(client)
        if not isinstance(fields, (list, tuple)) or len(fields) > 100 or any(
            not isinstance(f, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", f)
            for f in fields
        ):
            raise ValueError("原始证据字段须为最多100个明确字段名，不支持通配符")
        self.evidence_fields = tuple(fields)
        self.NEWS_LIST_BACK_FIELDS = tuple(dict.fromkeys((*self.NEWS_LIST_BACK_FIELDS, *fields)))

    def _map_article(self, item, keywords):
        # Preserve raw evidence without changing the established public aliases.
        return {**{k: item[k] for k in self.evidence_fields if k in item},
                **super()._map_article(item, keywords)}
