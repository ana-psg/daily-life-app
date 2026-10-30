"""QR code em SVG, sem biblioteca: modo byte, correção de erro média, versões 1 a 10.

Serve para o endereço do app no celular (cerca de 50 caracteres). Segue o padrão
ISO/IEC 18004; o desenho do algoritmo acompanha o gerador de referência de Nayuki.
"""

# Correção média (M): códigos de correção por bloco e número de blocos, por versão (índice 0 sem uso)
ECC_PER_BLOCK = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
NUM_BLOCKS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
FORMAT_M = 0  # bits de formato do nível M
MAX_VERSION = 10


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _raw_modules(ver: int) -> int:
    """Módulos livres para dados (tudo menos os padrões fixos)."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver]


def _codewords(data: bytes) -> tuple[int, list[int]]:
    """Escolhe a menor versão e monta os bytes de dados + correção, já intercalados."""
    for ver in range(1, MAX_VERSION + 1):
        count_bits = 8 if ver <= 9 else 16
        if 4 + count_bits + 8 * len(data) <= _data_codewords(ver) * 8:
            break
    else:
        raise ValueError("Texto longo demais para o QR code.")
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in reversed(range(count_bits))]
    for byte in data:
        bits += [(byte >> i) & 1 for i in reversed(range(8))]
    capacity = _data_codewords(ver) * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < _data_codewords(ver):
        words.append(pad)
        pad ^= 0xEC ^ 0x11

    num_blocks, ecc_len = NUM_BLOCKS[ver], ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    num_short = num_blocks - raw % num_blocks
    short_len = raw // num_blocks
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(num_blocks):
        dat = words[k : k + short_len - ecc_len + (0 if i < num_short else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, divisor)
        if i < num_short:
            dat = [*dat, 0]
        blocks.append(dat + ecc)
    out = [
        blk[i]
        for i in range(len(blocks[0]))
        for j, blk in enumerate(blocks)
        if i != short_len - ecc_len or j >= num_short
    ]
    return ver, out


class _Grid:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def put(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self.put(6, i, i % 2 == 0)
            self.put(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.put(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.alignment_positions()
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.put(a, b, bit)
                self.put(b, a, bit)

    def alignment_positions(self) -> list[int]:
        if self.ver == 1:
            return []
        n = self.ver // 7 + 2
        step = (self.ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
        return list(reversed([self.size - 7 - i * step for i in range(n - 1)] + [6]))

    def format_bits(self, mask: int) -> None:
        data = FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = [(bits >> i) & 1 == 1 for i in range(15)]
        n = self.size
        for i in range(6):
            self.put(8, i, bit[i])
        self.put(8, 7, bit[6])
        self.put(8, 8, bit[7])
        self.put(7, 8, bit[8])
        for i in range(9, 15):
            self.put(14 - i, 8, bit[i])
        for i in range(8):
            self.put(n - 1 - i, 8, bit[i])
        for i in range(8, 15):
            self.put(8, n - 15 + i, bit[i])
        self.put(8, n - 8, True)

    def codewords(self, words: list[int]) -> None:
        n, i = self.size, 0
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.fixed[y][x] and i < len(words) * 8:
                        self.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        rules = [
            lambda x, y: (x + y) % 2 == 0,
            lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        ]
        rule = rules[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fixed[y][x] and rule(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        """Pontuação do desenho (sequências, blocos 2x2, falsos cantos, equilíbrio): menor é melhor."""
        n, score = self.size, 0
        for line in [*self.dark, *zip(*self.dark, strict=True)]:
            run, prev = 0, None
            for cell in line:
                run = run + 1 if cell == prev else 1
                prev = cell
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
        for y in range(n - 1):
            for x in range(n - 1):
                c = self.dark[y][x]
                if c == self.dark[y][x + 1] == self.dark[y + 1][x] == self.dark[y + 1][x + 1]:
                    score += 3
        # padrões parecidos com os quadrados de canto (1:1:3:1:1) confundem o leitor
        finder_a, finder_b = "10111010000", "00001011101"
        for line in [*self.dark, *zip(*self.dark, strict=True)]:
            text = "0000" + "".join("1" if c else "0" for c in line) + "0000"
            score += 40 * (text.count(finder_a) + text.count(finder_b))
        dark = sum(map(sum, self.dark))
        score += abs(dark * 20 - n * n * 10) // (n * n) * 10
        return score


def matrix(text: str) -> list[list[bool]]:
    ver, words = _codewords(text.encode("utf-8"))
    best, best_score = None, None
    for mask in range(8):
        grid = _Grid(ver)
        grid.function_patterns()
        grid.codewords(words)
        grid.apply_mask(mask)
        grid.format_bits(mask)
        score = grid.penalty()
        if best_score is None or score < best_score:
            best, best_score = grid, score
    return best.dark


def svg(text: str, quiet: int = 4) -> str:
    """QR code em SVG (escuro sobre branco, mesmo no tema escuro, para a câmera ler)."""
    grid = matrix(text)
    n = len(grid) + quiet * 2
    path = "".join(
        f"M{x + quiet} {y + quiet}h1v1h-1z"
        for y, row in enumerate(grid)
        for x, cell in enumerate(row)
        if cell
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges" '
        f'role="img" aria-label="QR code do endereço"><rect width="{n}" height="{n}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/></svg>'
    )
