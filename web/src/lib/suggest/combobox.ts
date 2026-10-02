import type { Suggestion } from "@/lib/api/types";

export const MIN_QUERY_LENGTH = 3;

export interface ComboboxState {
  /** The normalised text the suggestions belong to. */
  query: string;
  suggestions: readonly Suggestion[];
  /** -1 means no option is active, so Enter submits the typed text. */
  activeIndex: number;
  /** Set by Escape, Tab, blur or a selection; cleared by the next edit. */
  dismissed: boolean;
}

export type NavigationKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

export type ComboboxAction =
  | { type: "typed"; text: string }
  | { type: "received"; query: string; suggestions: readonly Suggestion[] }
  | { type: "failed"; query: string }
  | { type: "navigate"; key: NavigationKey }
  | { type: "dismiss" }
  | { type: "reset" };

export const initialComboboxState: ComboboxState = {
  query: "",
  suggestions: [],
  activeIndex: -1,
  dismissed: false,
};

export function normalizeQuery(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

export function isOpen(state: ComboboxState): boolean {
  return !state.dismissed && state.suggestions.length > 0;
}

export function comboboxReducer(
  state: ComboboxState,
  action: ComboboxAction,
): ComboboxState {
  switch (action.type) {
    case "typed": {
      const query = normalizeQuery(action.text);
      if (query.length < MIN_QUERY_LENGTH) {
        return { ...initialComboboxState, query };
      }
      if (query === state.query) {
        return state.activeIndex === -1 ? state : { ...state, activeIndex: -1 };
      }
      // The previous list stays up until the new one arrives, which avoids a
      // flicker on every keystroke. No option stays active, because it no
      // longer matches what was typed.
      return { ...state, query, activeIndex: -1, dismissed: false };
    }

    case "received":
      // A response for text that has since changed must never replace the
      // list for the current text.
      if (action.query !== state.query) return state;
      return { ...state, suggestions: action.suggestions, activeIndex: -1 };

    case "failed":
      if (action.query !== state.query) return state;
      return { ...state, suggestions: [], activeIndex: -1 };

    case "navigate": {
      const count = state.suggestions.length;
      if (count === 0) return state;
      const reopening = state.dismissed;
      const current = reopening ? -1 : state.activeIndex;
      let activeIndex: number;
      switch (action.key) {
        case "ArrowDown":
          activeIndex = (current + 1) % count;
          break;
        case "ArrowUp":
          activeIndex = current <= 0 ? count - 1 : current - 1;
          break;
        case "Home":
          activeIndex = 0;
          break;
        case "End":
          activeIndex = count - 1;
          break;
      }
      return { ...state, dismissed: false, activeIndex };
    }

    case "dismiss":
      return state.dismissed && state.activeIndex === -1
        ? state
        : { ...state, dismissed: true, activeIndex: -1 };

    case "reset":
      return initialComboboxState;
  }
}

export function optionId(listboxId: string, index: number): string {
  return `${listboxId}-option-${index}`;
}

export function describeCount(count: number): string {
  if (count === 0) return "";
  return `${count} ${count === 1 ? "suggestion" : "suggestions"} available`;
}
