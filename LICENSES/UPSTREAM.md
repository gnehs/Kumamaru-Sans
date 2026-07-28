# Upstream font attribution and distribution notice

## IBM Plex Sans TC

Kumamaru Sans is a modified-font workflow intended to operate on a
user-supplied copy of IBM Plex Sans TC Regular. IBM Plex is an IBM typeface
project; its official source and release information are available from
[IBM/plex](https://github.com/IBM/plex).

The IBM Plex license declares:

```text
Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"
```

IBM Plex font software is licensed under the SIL Open Font License, Version
1.1. A copy is included in [OFL-1.1.txt](OFL-1.1.txt). The repository-level
`LICENSE` applies only to this tool's source code and documentation, never to
an upstream font binary or a generated modified font.

## Requirements for generated fonts

A generated Kumamaru Sans font is a Modified Version under OFL 1.1. When
redistributing it, include:

- the original IBM copyright notice and Reserved Font Name declaration;
- the complete SIL Open Font License 1.1 text;
- a clear statement that Kumamaru Sans is a modified version based on IBM Plex
  Sans TC; and
- accurate metadata that identifies the modified font as `Kumamaru Sans`
  (traditional Chinese name: `熊丸體`).

`Plex` is a Reserved Font Name. Do not use it in a generated modified font's
primary user-facing name, family, full name, or PostScript name unless the
relevant copyright holder grants explicit written permission. Do not claim or
imply IBM endorsement of Kumamaru Sans.

The tool must preserve upstream attribution in the font copyright and license
metadata, add a modified-version notice, and distribute the generated font
under OFL 1.1. Before public release, verify the exact upstream font version,
its embedded metadata, and the final generated metadata.

## Sources consulted

- [IBM Plex license](https://github.com/IBM/plex/blob/master/LICENSE.txt)
- [SIL OFL: modifying and redistributing OFL fonts](https://openfontlicense.org/how-to-modify-ofl-fonts/)
- [SIL OFL: Reserved Font Names](https://openfontlicense.org/ofl-reserved-font-names/)
