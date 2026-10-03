"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";

import { useTheme } from "@/hooks/useTheme";
import { LOGIN_ITEM, NAV_ITEMS, SETTINGS_ITEM, SITE_NAME } from "@/lib/site";

import { BrandMark } from "./BrandMark";
import styles from "./MobileMenu.module.css";

const FOCUSABLE = "a[href], button:not([disabled])";

/**
 * Phones have no header. A round button floats top-right and opens this
 * dropdown with the brand, every page and the theme switch. Hidden by CSS from
 * 40rem up, where the header takes over.
 */
export function MobileMenu() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const [openPath, setOpenPath] = useState(pathname);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const panelId = useId();

  // Navigating anywhere closes the menu.
  if (openPath !== pathname) {
    setOpenPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>("a[href]")?.focus();

    function onPointerDown(event: globalThis.PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
      return;
    }
    if (event.key !== "Tab") return;
    // Keep Tab inside the button and the panel while the menu is open.
    const items = [
      ...(buttonRef.current ? [buttonRef.current] : []),
      ...Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []),
    ];
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    const active = document.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  // A link to the page already open does not change the path, so close here too.
  function handlePanelClick(event: MouseEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest("a[href]")) setOpen(false);
  }

  const themeLabel = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";

  return (
    <div ref={rootRef} className={styles.root} onKeyDown={handleKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        className={styles.button}
        aria-label="Menu"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={styles.icon}>
          {open ? (
            <path d="M6 6l12 12M18 6L6 18" />
          ) : (
            <path d="M4 7h16M4 12h16M4 17h16" />
          )}
        </svg>
      </button>

      <nav
        ref={panelRef}
        id={panelId}
        className={styles.panel}
        aria-label="Site menu"
        hidden={!open}
        onClick={handlePanelClick}
      >
        {open ? (
          <ul className={styles.list}>
            <li>
              <Link className={`${styles.row} ${styles.brand}`} href="/" prefetch={false}>
                <BrandMark className={styles.mark} />
                <span>{SITE_NAME}</span>
              </Link>
            </li>
            {[...NAV_ITEMS, SETTINGS_ITEM, LOGIN_ITEM].map(({ href, label }) => (
              <li key={href}>
                <Link
                  className={styles.row}
                  href={href}
                  prefetch={false}
                  aria-current={pathname === href ? "page" : undefined}
                >
                  {label}
                </Link>
              </li>
            ))}
            <li>
              <button
                type="button"
                className={`${styles.row} ${styles.themeRow}`}
                onClick={toggle}
                aria-label={themeLabel}
              >
                {themeLabel}
              </button>
            </li>
          </ul>
        ) : null}
      </nav>
    </div>
  );
}
