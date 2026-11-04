# XSS attempts

<script>window.__pwned = 1</script>

<img src=x onerror="window.__pwned = 2">

<iframe src="https://evil.example"></iframe>

<a href="javascript:alert(3)" onclick="alert(4)">raw anchor</a>

Inline <b onmouseover="alert(5)">bold</b> and <script>alert(6)</script> in a paragraph.

[js link](javascript:alert(7))
[JS link](JaVaScRiPt:alert(8))
[data link](data:text/html;base64,PHNjcmlwdD5hbGVydCg5KTwvc2NyaXB0Pg==)
[vbs link](vbscript:msgbox(10))
[entity link](&#106;avascript:alert(11))
[protocol relative](//evil.example/x)
[ok link](https://example.com)

![js image](javascript:alert(12))
![data image](data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9ImFsZXJ0KDEzKSI+)
![remote tracker](https://evil.example/pixel.gif)
![onerror" onerror="alert(14)](./a.png)

# Heading <img src=x onerror=alert(15)>

```html
<script>alert(16)</script>
```

| a | b |
|---|---|
| <script>alert(17)</script> | `<img src=x onerror=alert(18)>` |

[ref link][evil]

[evil]: javascript:alert(19) "title"

<style>body { display: none }</style>
<svg onload="alert(20)"></svg>
<form action="https://evil.example"><input name="x"></form>
