export const ADDRESS_MIN_LENGTH = 3;
export const ADDRESS_MAX_LENGTH = 200;
export const ADDRESS_PARAM = "address";

export type AddressValidation =
  | { ok: true; value: string }
  | { ok: false; message: string };

export function validateAddress(raw: string): AddressValidation {
  const value = raw.trim().replace(/\s+/g, " ");

  if (value.length === 0) {
    return { ok: false, message: "Enter an address to score." };
  }
  if (value.length < ADDRESS_MIN_LENGTH) {
    return {
      ok: false,
      message: `Enter at least ${ADDRESS_MIN_LENGTH} characters, such as a street and city.`,
    };
  }
  if (value.length > ADDRESS_MAX_LENGTH) {
    return {
      ok: false,
      message: `Addresses can be at most ${ADDRESS_MAX_LENGTH} characters.`,
    };
  }
  return { ok: true, value };
}

export function resultHref(address: string): string {
  return `/?${new URLSearchParams({ [ADDRESS_PARAM]: address })}`;
}
