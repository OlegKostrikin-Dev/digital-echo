FROM node:20-alpine

WORKDIR /app

# Только манифесты — для кэша слоёв
COPY apps/web/package.json ./apps/web/package.json

WORKDIR /app/apps/web

RUN npm install

EXPOSE 3000

CMD ["npm", "run", "dev"]
