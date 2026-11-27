const swaggerJsdoc = require("swagger-jsdoc");

const options = {
  definition: {
    openapi: "3.0.0",
    info: {
      title: "Cloud Photo Gallery API",
      version: "1.0.0",
      description: "Backend API for albums, cloud photo upload, Entra ID authentication and photo processing status."
    },
    servers: [{ url: "http://localhost:3000", description: "Local development" }],
    components: {
      securitySchemes: {
        bearerAuth: { type: "http", scheme: "bearer", bearerFormat: "JWT" }
      }
    }
  },
  apis: ["./src/routes/*.js"]
};

module.exports = swaggerJsdoc(options);
