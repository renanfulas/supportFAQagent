```markdown
# supportFAQagent Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill covers the development patterns and conventions used in the `supportFAQagent` TypeScript codebase. It provides guidance on file organization, import/export styles, and testing patterns to ensure consistency and maintainability. While no specific framework is used, the repository follows clear conventions for code structure and naming.

## Coding Conventions

### File Naming

- **Style:** kebab-case
- **Example:**  
  ```text
  support-faq-agent.ts
  faq-handler.test.ts
  ```

### Import Style

- **Style:** Relative imports
- **Example:**
  ```typescript
  import { getFAQ } from './faq-handler';
  ```

### Export Style

- **Style:** Named exports
- **Example:**
  ```typescript
  // In faq-handler.ts
  export function getFAQ(question: string): string { ... }
  ```

### Commit Patterns

- **Type:** Freeform messages (no strict prefixes)
- **Average Length:** ~34 characters
- **Example:**
  ```
  Add basic FAQ handler logic
  ```

## Workflows

### Adding a New FAQ Handler
**Trigger:** When you need to add logic for handling new FAQ entries.
**Command:** `/add-faq-handler`

1. Create a new file using kebab-case, e.g., `new-faq-handler.ts`.
2. Implement your handler function and export it as a named export.
   ```typescript
   export function handleNewFAQ(question: string): string { ... }
   ```
3. Import your handler in the main agent file using a relative import.
   ```typescript
   import { handleNewFAQ } from './new-faq-handler';
   ```
4. Write a corresponding test file named `new-faq-handler.test.ts`.

### Running Tests
**Trigger:** Before committing or merging changes to ensure code correctness.
**Command:** `/run-tests`

1. Locate all test files matching the pattern `*.test.*`.
2. Use your preferred test runner (framework not specified).
3. Run tests and verify all pass.
   ```bash
   # Example with a generic test runner
   npx ts-node faq-handler.test.ts
   ```

### Refactoring Code
**Trigger:** When improving existing logic or reorganizing files.
**Command:** `/refactor-code`

1. Rename or move files using kebab-case.
2. Update all relative imports to reflect new paths.
3. Ensure all exports remain named.
4. Run all tests to confirm nothing is broken.

## Testing Patterns

- **Test File Naming:** Use the pattern `*.test.*`, e.g., `faq-handler.test.ts`.
- **Framework:** Not specified; use assertions and structure consistent with your team's practices.
- **Example:**
  ```typescript
  import { getFAQ } from './faq-handler';

  describe('getFAQ', () => {
    it('returns the correct answer', () => {
      expect(getFAQ('How to reset password?')).toBe('Follow these steps...');
    });
  });
  ```

## Commands

| Command            | Purpose                                               |
|--------------------|-------------------------------------------------------|
| /add-faq-handler   | Add a new FAQ handler module                          |
| /run-tests         | Run all test files                                    |
| /refactor-code     | Refactor code and update imports/exports accordingly  |
```
