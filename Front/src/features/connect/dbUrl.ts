// 팀 DB 접속 주소(postgresql://계정:비밀번호@서버:포트/이름)를 풀어 읽고, 항목별로 넣은 값을 주소 한 줄로 합친다.
// 주소 칸은 가려져 있으므로, 붙여 넣은 값이 무엇인지는 여기서 푼 값(비밀번호 제외)으로 보여 준다.

export interface DbUrlParts { host: string; port: string; name: string; user: string }

const DEFAULT_PORT = "5432"

/** 주소를 풀어 읽는다. postgresql:// · postgres:// 주소가 아니거나 서버가 없으면 null. 비밀번호는 돌려주지 않는다. */
export function parseDbUrl(value: string): DbUrlParts | null {
  try {
    const u = new URL(value.trim())
    if (!/^postgres(ql)?:$/.test(u.protocol) || !u.hostname) return null
    return { host: u.hostname, port: u.port || DEFAULT_PORT, name: safeDecode(u.pathname.replace(/^\//, "")), user: safeDecode(u.username) }
  } catch { return null }
}

/** 항목별 입력 → 주소 한 줄. 계정·비밀번호·이름에 든 특수문자는 주소에 쓸 수 있게 바꾼다. */
export function buildDbUrl(p: DbUrlParts & { password: string }): string {
  const user = p.user.trim()
  const auth = user ? `${encodeURIComponent(user)}${p.password ? `:${encodeURIComponent(p.password)}` : ""}@` : ""
  return `postgresql://${auth}${p.host.trim()}:${p.port.trim() || DEFAULT_PORT}/${encodeURIComponent(p.name.trim())}`
}

function safeDecode(s: string): string {
  try { return decodeURIComponent(s) } catch { return s }
}
