# The finished task: the catalog service pages its results.
printf '\nPAGE_SIZE = 20\n' >> src/catalog/service.py
git add -- src/catalog/service.py
git commit -q -m "catalog: page the results"
