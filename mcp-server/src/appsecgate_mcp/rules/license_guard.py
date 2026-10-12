"""Лицензионный гвард Rules Bundle.

Проверяет совместимость лицензий бандлов с режимом поставки
(`distribution_mode: mit | commercial`). Базовое правило v1: сборка под MIT
не должна содержать бандлов с `redistribution: restricted` (например,
правил под Commons Clause) — иначе публикация нарушает лицензию.

См. дизайн v1 §1.1 и §9.
"""

from __future__ import annotations

from appsecgate_mcp.rules.manifest import (
    BundleEntry,
    DistributionMode,
    Redistribution,
    RulesManifest,
)


class LicenseGuard:
    """Валидатор лицензионной чистоты поставки.

    `check` возвращает список **ошибок** (пустой список — поставка чистая).
    `warnings` возвращает некритичные замечания. Гвард ничего не поднимает
    исключениями: решение о блокировке сборки принимает вызывающая сторона.
    """

    @staticmethod
    def _violating_bundles(
        manifest: RulesManifest,
        redistribution: Redistribution,
    ) -> list[BundleEntry]:
        return [b for b in manifest.bundles if b.redistribution == redistribution]

    @classmethod
    def check(
        cls,
        manifest: RulesManifest,
        distribution_mode: DistributionMode,
    ) -> list[str]:
        """Возвращает список ошибок совместимости лицензий.

        `mit` блокирует бандлы с `redistribution: restricted`.
        `commercial` допускает всё (ответственность на поставщике).
        """
        errors: list[str] = []
        if distribution_mode == DistributionMode.MIT:
            for bundle in cls._violating_bundles(manifest, Redistribution.RESTRICTED):
                errors.append(
                    f"bundle '{bundle.id}' has redistribution=restricted "
                    f"and cannot be shipped under distribution_mode=mit "
                    f"(license: {bundle.license or 'unknown'})"
                )
        return errors

    @classmethod
    def warnings(
        cls,
        manifest: RulesManifest,
        distribution_mode: DistributionMode,
    ) -> list[str]:
        """Некритичные замечания (не блокируют сборку)."""
        warnings: list[str] = []
        if distribution_mode == DistributionMode.MIT:
            for bundle in cls._violating_bundles(manifest, Redistribution.INTERNAL):
                warnings.append(
                    f"bundle '{bundle.id}' is marked redistribution=internal "
                    f"but is packaged in a mit build"
                )
        return warnings

    @classmethod
    def is_compatible(
        cls,
        manifest: RulesManifest,
        distribution_mode: DistributionMode,
    ) -> bool:
        """True, если ошибок совместимости нет."""
        return not cls.check(manifest, distribution_mode)
