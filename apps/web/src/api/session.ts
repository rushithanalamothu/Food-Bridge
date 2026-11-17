import type { Role } from './generated/workflow';

let token: string | undefined;
let organization: string | undefined;
export function setAccessToken(value?: string) {
  token = value;
}
export function setOrganization(value?: string) {
  organization = value || undefined;
}
export function sessionHeaders(role?: Role): Record<string, string> {
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(role ? { 'X-FoodBridge-Role': role } : {}),
    ...(organization ? { 'X-Organization-ID': organization } : {}),
  };
}
