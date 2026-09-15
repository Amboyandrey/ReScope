import { describe, expect, it } from "vitest";
import { originFor, tenantSlugFromHost } from "./tenant";

const ROOT = "rescope.localhost";

describe("tenantSlugFromHost", () => {
  it("returns the label directly under the root domain", () => {
    expect(tenantSlugFromHost("acme.rescope.localhost", ROOT)).toBe("acme");
  });
  it("ignores the port", () => {
    expect(tenantSlugFromHost("acme.rescope.localhost:3000", ROOT)).toBe("acme");
  });
  it("is case-insensitive", () => {
    expect(tenantSlugFromHost("ACME.ReScope.localhost", ROOT)).toBe("acme");
  });
  it("returns null for the root domain itself", () => {
    expect(tenantSlugFromHost("rescope.localhost:3000", ROOT)).toBeNull();
  });
  it("returns null for www", () => {
    expect(tenantSlugFromHost("www.rescope.localhost", ROOT)).toBeNull();
  });
  it("returns null for nested labels", () => {
    expect(tenantSlugFromHost("x.acme.rescope.localhost", ROOT)).toBeNull();
  });
  it("returns null for a different domain that merely ends with the root", () => {
    expect(tenantSlugFromHost("evilrescope.localhost", ROOT)).toBeNull();
  });
  it("returns null for a missing host or an invalid slug", () => {
    expect(tenantSlugFromHost(null, ROOT)).toBeNull();
    expect(tenantSlugFromHost("-bad.rescope.localhost", ROOT)).toBeNull();
    expect(tenantSlugFromHost("has_underscore.rescope.localhost", ROOT)).toBeNull();
  });
});

describe("originFor", () => {
  it("builds tenant and root origins", () => {
    expect(originFor("acme", ROOT, "http:", "3000")).toBe("http://acme.rescope.localhost:3000");
    expect(originFor(null, ROOT, "https:", "")).toBe("https://rescope.localhost");
  });
});
