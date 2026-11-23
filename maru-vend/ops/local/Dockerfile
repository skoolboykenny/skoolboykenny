# Maru Vend sample stack image (TEST / DEMO ONLY): PHP 8.3 CLI with the app and its dependencies.
# Dependencies are installed in the official Composer image, so no OS packages are needed.
FROM composer:2 AS deps
WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install -n --no-dev --no-progress --no-autoloader --ignore-platform-reqs
COPY . .
RUN composer dump-autoload -n --no-dev --optimize

FROM php:8.3-cli
RUN docker-php-ext-install pdo_mysql
WORKDIR /app
COPY --from=deps /app /app
ENV TZ=Africa/Gaborone
