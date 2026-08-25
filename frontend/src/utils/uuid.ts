export function newRequestId(): string {
  const random = () => Math.floor((1 + Math.random()) * 0x10000).toString(16).slice(1)
  return `${random()}${random()}-${random()}-4${random().slice(1)}-a${random().slice(1)}-${random()}${random()}${random()}`
}
