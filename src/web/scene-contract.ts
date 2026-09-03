import sceneV1Schema from "../../schemas/scene-v1.schema.json";
import { RequestValidationError } from "./request-errors";

type JsonObject = Record<string, unknown>;
type Schema = {
  $ref?: string;
  type?: string;
  required?: string[];
  properties?: Record<string, Schema>;
  additionalProperties?: boolean;
  items?: Schema;
  const?: unknown;
  enum?: unknown[];
  minLength?: number;
  minimum?: number;
  exclusiveMinimum?: number;
};

function object(value: unknown, path: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new RequestValidationError(`${path} must be an object`);
  return value as JsonObject;
}

function resolved(schema: Schema): Schema {
  if (!schema.$ref) return schema;
  const prefix = "#/$defs/";
  if (!schema.$ref.startsWith(prefix)) throw new Error(`Unsupported scene schema reference: ${schema.$ref}`);
  const name = schema.$ref.slice(prefix.length);
  const definitions = (sceneV1Schema as { $defs?: Record<string, Schema> }).$defs;
  const definition = definitions?.[name];
  if (!definition) throw new Error(`Missing scene schema definition: ${name}`);
  return definition;
}

function validate(value: unknown, source: Schema, path: string): void {
  const schema = resolved(source);
  if (schema.const !== undefined && value !== schema.const) throw new RequestValidationError(`${path} must be ${String(schema.const)}`);
  if (schema.enum && !schema.enum.includes(value)) throw new RequestValidationError(`${path} is not supported`);
  if (schema.type === "object") {
    const input = object(value, path);
    for (const key of schema.required ?? []) if (!(key in input)) throw new RequestValidationError(`${path}.${key} is required`);
    if (schema.additionalProperties === false) for (const key of Object.keys(input)) if (!schema.properties?.[key]) throw new RequestValidationError(`${path}.${key} is not allowed`);
    for (const [key, property] of Object.entries(schema.properties ?? {})) if (key in input) validate(input[key], property, `${path}.${key}`);
    return;
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) throw new RequestValidationError(`${path} must be a list`);
    for (const [index, item] of value.entries()) if (schema.items) validate(item, schema.items, `${path}[${index}]`);
    return;
  }
  if (schema.type === "string") {
    if (typeof value !== "string") throw new RequestValidationError(`${path} must be a string`);
    if (schema.minLength !== undefined && value.length < schema.minLength) throw new RequestValidationError(`${path} must be a non-empty string`);
    return;
  }
  if (schema.type === "boolean") {
    if (typeof value !== "boolean") throw new RequestValidationError(`${path} must be a boolean`);
    return;
  }
  if (schema.type === "number" || schema.type === "integer") {
    if (typeof value !== "number" || !Number.isFinite(value) || (schema.type === "integer" && !Number.isInteger(value))) throw new RequestValidationError(`${path} must be a ${schema.type}`);
    if (schema.minimum !== undefined && value < schema.minimum) throw new RequestValidationError(`${path} must be at least ${schema.minimum}`);
    if (schema.exclusiveMinimum !== undefined && value <= schema.exclusiveMinimum) throw new RequestValidationError(`${path} must be greater than ${schema.exclusiveMinimum}`);
  }
}

export function validateSceneV1(value: unknown): JsonObject {
  validate(value, sceneV1Schema as Schema, "scene");
  return structuredClone(value as JsonObject);
}
