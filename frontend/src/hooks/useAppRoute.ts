import { useState, useEffect, useCallback } from 'react';
import { getSavedSession, clearSession } from '../lib/auth.ts';
import { fetchCurrentUser } from "../lib/auth.ts";
import { UNAUTHORIZED_EVENT } from "../lib/api.ts";

export type AppRoute = 'landing' | 'home' | 'playground';

// When the app script loads: if URL hash is NOT "#home", clear the saved mock session
// so reloading the landing page always starts fresh and logged out
// if (typeof window !== 'undefined') {
//   const initialHash = window.location.hash.toLowerCase();
//   if (initialHash !== '#home') {
//     clearSession();
//   }
// }

export function useAppRoute(onNeedLogin?: () => void) {
  const [route, setRoute] = useState<AppRoute>(() => {
    if (typeof window === 'undefined') return 'landing';
    const hash = window.location.hash.toLowerCase();
    const session = getSavedSession();
    if (hash === '#home' && session) return 'home';
    if (hash === '#playground' && session) return 'playground';
    return 'landing';
  });

  const syncRoute = useCallback(() => {
    if (typeof window === 'undefined') return;
    const hash = window.location.hash.toLowerCase();
    const session = getSavedSession();

    if (hash === '#home') {
      if (session) {
        setRoute('home');
      } else {
        setRoute('landing');
        if (onNeedLogin) {
          onNeedLogin();
        } else {
          window.location.hash = '#login';
        }
      }
    } else if (hash === '#playground') {
      if (session) {
        setRoute('playground');
      } else {
        setRoute('landing');
        if (onNeedLogin) {
          onNeedLogin();
        } else {
          window.location.hash = '#login';
        }
      }
    } else {
      setRoute('landing');
    }
  }, [onNeedLogin]);

  useEffect(() => {
    syncRoute();
    window.addEventListener('hashchange', syncRoute);
    window.addEventListener('popstate', syncRoute);
    return () => {
      window.removeEventListener('hashchange', syncRoute);
      window.removeEventListener('popstate', syncRoute);
    };
  }, [syncRoute]);

  useEffect(() => {
    if (getSavedSession()) fetchCurrentUser().catch(() => { });
  }, []);

  useEffect(() => {
    const h = () => {
      clearSession();
      if (window.location.hash === '#home' || window.location.hash === '#playground')
        history.pushState(null, '', window.location.pathname + window.location.search);
      setRoute('landing');
      onNeedLogin?.();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, h);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, h);
  }, [onNeedLogin]);

  const navigate = useCallback((target: AppRoute) => {
    if (target === 'home') {
      if (window.location.hash !== '#home') {
        history.pushState(null, '', '#home');
      }
      setRoute('home');
    } else if (target === 'playground') {
      if (window.location.hash !== '#playground') {
        history.pushState(null, '', '#playground');
      }
      setRoute('playground');
    } else {
      if (window.location.hash === '#home' || window.location.hash === '#playground') {
        const cleanUrl = window.location.pathname + window.location.search;
        history.pushState(null, '', cleanUrl);
      }
      setRoute('landing');
    }
  }, []);

  const logout = useCallback(() => {
    clearSession();
    if (window.location.hash === '#home' || window.location.hash === '#playground') {
      const cleanUrl = window.location.pathname + window.location.search;
      history.pushState(null, '', cleanUrl);
    }
    setRoute('landing');
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, []);

  return {
    route,
    navigate,
    logout,
  };
}
