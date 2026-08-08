# Third-party notices

## Vendored: CaliCastle/seedhub-cli

- **License:** MIT
- **Copyright:** 2026 Cali Castle
- **Source:** <https://github.com/CaliCastle/seedhub-cli>
- **Local license:** [`vendor/seedhub-cli/LICENSE`](vendor/seedhub-cli/LICENSE)

The original local snapshot did not retain a provable exact upstream commit,
so this repository does not claim byte identity with an upstream revision. The
release audit compared the code and licensing against upstream `main` at
`081b273c5842560e7be15949a5970dc3da25ede0`; this hash is an audit reference,
not a claim that the vendored file was produced directly from that commit.

Local patches:

- use the code-owned live SeedHub base and prevent environment redirection;
- add JSON output and resource-type filtering;
- resolve Baidu share links with restricted intermediate redirects and keep
  extraction codes separate;
- add an explicit file-backed fixture seam using reserved `.example` hosts.

## Runtime dependency: cloudscraper

- **License:** MIT
- **Source:** <https://github.com/VeNoMouS/cloudscraper>
- **Distribution:** installed from the pinned entry in `requirements.txt`; not
  vendored in this repository.

cloudscraper retains its upstream copyright and license. The project's MIT
license does not replace or reattribute that upstream work.

## External tool and installation reference: bdpan-storage

- **License:** Apache-2.0
- **Source:** <https://github.com/baidu-netdisk/bdpan-storage>
- **Release audit reference:** upstream `main` at
  `bec0fae6416471446172a253b8b95e966177791b`
- **Distribution:** not vendored and not silently downloaded by this project.

The `bdpan` executable and the official installation/login guidance remain
separate upstream works. Users install them from Baidu's official repository;
their Apache-2.0 terms are not replaced by this project's MIT license.

## Other Python dependencies

Other packages are installed from the exact versions in `requirements.txt`
and retain their respective upstream licenses and copyright notices. Packaging
or redistributing dependency artifacts requires a fresh license audit.
