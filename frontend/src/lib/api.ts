   const TOKEN_KEY = 'pebble_token';
   export const USER_KEY = 'pebble_user';
   export const UNAUTHORIZED_EVENT = 'pebble:unauthorized';
   export const API_BASE =
     ((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim().replace(/\/+$/, '') || '/api';

   export class ApiError extends Error {
     status: number;
     data?: any;
     constructor(message: string, status: number, data?: any) {
       super(message); this.name = 'ApiError'; this.status = status; this.data = data;
     }
   }

   export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
   export const setToken = (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch {} };
   export const clearStoredAuth = () => {
     try {
       localStorage.removeItem(TOKEN_KEY);
       localStorage.removeItem(USER_KEY);
       localStorage.removeItem('pebble_chats');
       localStorage.removeItem('pebble_active_chat');
     } catch {}
   };

   export function extractErrorMessage(data: any): string {
     if (typeof data?.detail === 'string' && data.detail.trim()) {
       return data.detail.trim();
     }
     if (Array.isArray(data?.detail) && data.detail.length > 0) {
       const msgs = data.detail
         .map((item: any) => {
           if (typeof item === 'string') return item.trim();
           if (typeof item?.msg === 'string') {
             let m = item.msg.trim();
             if (m.startsWith('Value error, ')) m = m.slice('Value error, '.length);
             return m;
           }
           return '';
         })
         .filter(Boolean);
       if (msgs.length > 0) {
         return msgs.join('. ');
       }
     }
     if (typeof data?.message === 'string' && data.message.trim()) {
       return data.message.trim();
     }
     return 'Something went wrong. Please try again.';
   }

   export async function request<T>(
     path: string,
     opts: { method?: 'GET'|'POST'|'PATCH'|'DELETE'; body?: unknown; auth?: boolean; signal?: AbortSignal } = {}
   ): Promise<T> {
     const { method = 'GET', body, auth = true, signal } = opts;
     const headers: Record<string, string> = { Accept: 'application/json' };
     if (body !== undefined) headers['Content-Type'] = 'application/json';
     if (auth) { const t = getToken(); if (t) headers.Authorization = `Bearer ${t}`; }

     let res: Response;
     try {
       res = await fetch(`${API_BASE}${path}`, {
         method, headers, signal,
         body: body !== undefined ? JSON.stringify(body) : undefined,
       });
     } catch (err) {
       if ((err as any)?.name === 'AbortError') throw err;
       throw new Error('Cannot reach the server. Please check your connection and try again.');
     }

     let data: any = null;
     const text = await res.text();
     if (text) { try { data = JSON.parse(text); } catch { data = null; } }

     if (!res.ok) {
       if (res.status === 401 && auth) {
         clearStoredAuth();
         window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
       }
       const message = extractErrorMessage(data);
       const error = new Error(message);
       (error as any).status = res.status;
       (error as any).data = data;
       throw error;
     }
     return data as T;
   }