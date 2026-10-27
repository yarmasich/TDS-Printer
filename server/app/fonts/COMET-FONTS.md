# Fonts from the user-supplied Comet repository

The source revision, original download URL, SHA-256, embedded copyright and
license metadata for each file are recorded in `comet-fonts-sources.json`.
These are the actual supplied files, not substituted or synthesized faces.

The renderer and the Font family menu expose 12 added text families plus Microsoft Sans Serif Regular (25 files).
Rubik has all ten supplied faces, Roboto has Regular and Medium, and San Francisco
has Regular, Bold and Thin. The other added families have Regular only. Microsoft Sans Serif Regular uses the supplied file. The existing Bold face remains
unchanged because the supplied repository contains no Microsoft Sans Serif Bold file.
Icon fonts are excluded because they are not text fonts for cable labels.

Roboto's supplied files identify Apache 2.0; see `Comet-Roboto-LICENSE.txt`.
Rubik identifies SIL OFL 1.1; see `Comet-Rubik-OFL.txt` and the original embedded
copyright notices in the manifest. Files retain their embedded notices.

The Microsoft/Monotype and Apple fonts in this source have separate license
terms; their appearance in a public GitHub repository is not an open-font license
or proof of permission to redistribute them. The manifest preserves the available
notices without treating the repository's license as a font license. Confirm
appropriate rights for these files before distributing/deploying the application.

TTF and OTF assets are included in Python package data. Preview and print use the
same server-side files; these assets are not served as browser webfonts. No schema
migration is needed: template font family and style are existing string columns.
