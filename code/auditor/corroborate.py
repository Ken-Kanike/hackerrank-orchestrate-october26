"""Identity corroboration of data-catalog links (limitations D2).

A LINK_RESOURCE_IDENTITY event says "resource R belongs to person P"; the screenshot / PDF captured just before it shows what the
artifact actually contains. Activities are claims, so the link is checked against the artifact's own identifiers:
  corroborated  an identifier on the artifact resolves to the same user as the catalog event   -> keep
  contradicted  identifiers resolve only to a *different known user*                            -> drop the link, flag
  unverified    identifiers are unknown to the directory (or nothing could be read)            -> keep, flag for review
"""
from __future__ import annotations

from .evidence import Obs


def corroborate(obs: list[Obs], vision: dict | None, directory) -> tuple[list[Obs], list[dict]]:
    flags, keep = [], []
    for o in obs:
        if o.kind != "catalog":
            keep.append(o); continue
        v = (vision or {}).get(o.fid)
        if not v:
            flags.append({"fid": o.fid, "rid": o.rid, "flag": "catalog_artifact_unread",
                          "detail": "no vision/OCR reading of the artifact; link and state rest on the catalog event"})
            keep.append(o); continue
        art = {x.lower() for x in v.get("emails", [])} | {x.lower() for x in v.get("users", [])}
        if not art:
            keep.append(o); continue
        subj_uids = set().union(*(directory.owner.get(k, set()) for k in o.keys)) if o.keys else set()
        art_uids = set().union(*(directory.owner.get(k, set()) for k in art))
        if art_uids & subj_uids:
            keep.append(o)
        elif art_uids and subj_uids:
            flags.append({"fid": o.fid, "rid": o.rid, "flag": "catalog_contradicted",
                          "detail": f"artifact identifiers resolve to {sorted(art_uids)}, catalog says {sorted(subj_uids)}; link dropped"})
        else:
            flags.append({"fid": o.fid, "rid": o.rid, "flag": "catalog_unverified_identity",
                          "detail": f"artifact shows identifiers {sorted(art)[:3]} unknown to the directory; link kept"})
            keep.append(o)
    return keep, flags
