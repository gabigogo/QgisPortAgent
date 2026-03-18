"""Quick analysis script for .tbx binary reverse engineering."""
import olefile, struct, sys

WORKSPACE = r"D:\01_dev\a-Arc2Qgis"


def find_wstrs(data):
    """Scan bytes for 4-byte LE char-count prefixed UTF-16-LE strings followed by 00 00."""
    results = []
    i = 0
    while i < len(data) - 6:
        n = struct.unpack_from('<I', data, i)[0]
        if 1 <= n <= 2000:
            start = i + 4
            nbytes = n * 2
            if start + nbytes + 2 <= len(data):
                blob = data[start:start + nbytes]
                try:
                    s = blob.decode('utf-16-le')
                    if all(c.isprintable() or c in '\r\n\t' for c in s):
                        term = data[start + nbytes:start + nbytes + 2]
                        if term == b'\x00\x00':
                            results.append({'offset': i, 'char_count': n, 'string': s})
                            i = start + nbytes + 2
                            continue
                except Exception:
                    pass
        i += 1
    return results


def hex_dump(data, start=0, width=16, max_rows=32):
    lines = []
    end = min(len(data), start + max_rows * width)
    for i in range(start, end, width):
        c = data[i:i + width]
        h = ' '.join(f'{b:02x}' for b in c).ljust(width * 3)
        a = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in c)
        lines.append(f'  {i:06x}  {h}  {a}')
    return '\n'.join(lines)


def analyze_tool_stream(label, path, stream_name='Tool0'):
    print(f'\n{"="*72}')
    print(f'  {label} : {stream_name}')
    print(f'{"="*72}')
    with olefile.OleFileIO(str(path)) as ole:
        data = ole.openstream([stream_name]).read()
    print(f'  Total bytes: {len(data):,}')

    # First 16 bytes header
    print('\n  -- Header (first 16 bytes) --')
    print(hex_dump(data, max_rows=1))

    # Parse header fields
    f0, f1, f2 = struct.unpack_from('<IHH', data, 0)
    print(f'  [0x00] uint32 = {f0}')
    print(f'  [0x04] uint16 = {f1}')
    print(f'  [0x06] uint16 = {f2}')

    # Extract all WSTR strings
    print('\n  -- WSTR strings (first 50) --')
    strings = find_wstrs(data)
    for s in strings[:50]:
        txt = s['string'][:100].replace('\r', '<CR>').replace('\n', '<LF>')
        print(f"    +0x{s['offset']:06x}  n={s['char_count']:>5}  {txt!r}")
    if len(strings) > 50:
        print(f'    ... ({len(strings) - 50} more)')


PARAM_GUID = bytes([0x12,0x6f,0xd0,0x31,0x00,0x3f,0xf8,0x47,0xa6,0x57,0x3a,0x2e,0x4e,0xa8,0x5f,0xe2])


def find_param_guids(data: bytes):
    """Find all parameter-marker-GUID positions."""
    positions = []
    pos = 0
    while True:
        idx = data.find(PARAM_GUID, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + 1
    return positions


def read_wstr(data: bytes, offset: int):
    """Read one 4-byte-char-count prefixed UTF-16-LE string. Returns (string, next_offset)."""
    n = struct.unpack_from('<I', data, offset)[0]
    start = offset + 4
    raw = data[start:start + n * 2]
    s = raw.decode('utf-16-le', errors='replace')
    return s, start + n * 2 + 2  # skip null terminator


if __name__ == '__main__':
    corpus = r'D:\01_dev\a-Arc2Qgis\research\corpus'

    # 1. Show PARAM_GUID occurrences and surrounding bytes per-param
    with olefile.OleFileIO(f'{corpus}/sun_position_arcmap.tbx') as ole:
        data = ole.openstream(['Tool0']).read()

    positions = find_param_guids(data)
    print(f'sun_position Tool0: PARAM_GUID at {len(positions)} locations\n')
    for i, p in enumerate(positions):
        before4 = data[p - 4:p].hex(' ') if p >= 4 else '??'
        after8  = data[p + 16:p + 24].hex(' ')
        # Try to read the first WSTR after GUID + 2 bytes
        wstr_off = p + 16 + 2
        try:
            name, _ = read_wstr(data, wstr_off)
        except Exception:
            name = '??'
        print(f'  [{i}] 0x{p:06x}  pre={before4}  post={after8}  name={name!r}')
    
    print()
    # 2. Verify param count field
    analyze_tool_stream('sun_pos arcmap', f'{corpus}/sun_position_arcmap.tbx', 'Tool0')
