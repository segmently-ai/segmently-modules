# The team declared the new role in its config; no module has its doc yet.
printf '\n[roles.reviewer]\norder = 60\nstandard = true\ndescription = "What a reviewer checks in a change to the module"\n' >> .modsys/config.toml
git add -- .modsys/config.toml
git commit -q -m "declare the reviewer role"
