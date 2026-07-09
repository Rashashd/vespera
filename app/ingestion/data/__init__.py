"""Bundled ingestion data resources (package marker).

Makes ``app.ingestion.data`` an importable package so ``importlib.resources`` can load the
shipped ``mesh_terms.txt`` MeSH vocabulary (see ``app/ingestion/mesh.py``). Not an orphan —
do not remove.
"""
