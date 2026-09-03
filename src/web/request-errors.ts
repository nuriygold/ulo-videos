export class ClientRequestError extends Error {
  constructor(message: string, readonly status: 400 | 404 | 409 = 400) {
    super(message);
  }
}

export class RequestValidationError extends ClientRequestError {
  constructor(message: string) {
    super(message, 400);
  }
}

export class WorkspaceOwnershipError extends ClientRequestError {
  constructor(message: string, status: 404 | 409 = 404) {
    super(message, status);
  }
}
