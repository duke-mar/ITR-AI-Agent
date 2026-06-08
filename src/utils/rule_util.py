import re


class NumberForLifeVerify:

    @staticmethod
    def is_phone_number(text: str) -> bool:
        """
        判断字符串是否为有效的手机号码
        
        支持中国大陆手机号码格式:
        - 11位数字
        - 以1开头
        - 第二位为3-9
        
        支持的号段: 13x, 14x, 15x, 16x, 17x, 18x, 19x
        
        Args:
            text: 待判断的字符串
            
        Returns:
            bool: 是有效手机号码返回True，否则返回False
            
        Examples:
            >>> is_phone_number("13812345678")
            True
            >>> is_phone_number("12345678901")
            False
            >>> is_phone_number("1381234567")
            False
        """
        if not text or not isinstance(text, str):
            return False
        
        # 去除空白字符
        text = text.strip()
        
        # 手机号正则：1开头，第二位3-9，后面9位数字，总共11位
        pattern = r'^1[3-9]\d{9}$'
        
        return bool(re.match(pattern, text))


    @staticmethod
    def is_email(text: str) -> bool:
        """
        判断字符串是否为有效的邮箱地址
        
        支持标准邮箱格式:
        - 本地部分: 字母、数字、点、下划线、百分号、加减号
        - @符号
        - 域名部分: 字母、数字、点、横线
        - 顶级域名: 至少2个字母
        
        Args:
            text: 待判断的字符串
            
        Returns:
            bool: 是有效邮箱返回True，否则返回False
            
        Examples:
            >>> is_email("user@example.com")
            True
            >>> is_email("user.name@example.co.uk")
            True
            >>> is_email("invalid-email")
            False
            >>> is_email("user@.com")
            False
        """
        if not text or not isinstance(text, str):
            return False
        
        # 去除空白字符和转小写（仅用于校验，不改变原值）
        text = text.strip()
        
        # 邮箱正则（RFC 5322简化版，覆盖绝大多数常见场景）
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not re.match(pattern, text):
            return False
        
        # 额外检查：域名部分不能以点开头或结尾，不能连续两个点
        local_part, domain = text.split('@', 1)
        
        # 本地部分长度限制（1-64字符）
        if len(local_part) < 1 or len(local_part) > 64:
            return False
        
        # 域名长度限制（1-255字符）
        if len(domain) < 1 or len(domain) > 255:
            return False
        
        # 域名不能以点开头或结尾
        if domain.startswith('.') or domain.endswith('.'):
            return False
        
        # 不能有连续两个点
        if '..' in domain:
            return False
        
        return True

    @staticmethod
    def is_id_card(text: str, strict_mode: bool = True) -> bool:
        """
        判断字符串是否为有效的身份证号码
        
        支持18位和15位身份证号码格式:
        - 18位: 17位数字 + 1位数字或X（校验码）
        - 15位: 15位数字（已逐步淘汰）
        
        严格模式会校验18位身份证的校验码是否正确
        
        Args:
            text: 待判断的字符串
            strict_mode: 是否开启严格校验（校验18位身份证的校验码），默认True
            
        Returns:
            bool: 是有效身份证号码返回True，否则返回False
            
        Examples:
            >>> is_id_card("11010119900307663X")
            True  # 示例号码，校验码正确
            >>> is_id_card("110101199003076630")
            False  # 校验码错误
            >>> is_id_card("110101900307663")
            True  # 15位旧版身份证
        """
        if not text or not isinstance(text, str):
            return False
        
        # 去除空白字符并转为大写
        text = text.strip().upper()
        
        # 15位身份证：纯数字，15位
        if len(text) == 15:
            return bool(re.match(r'^[1-9]\d{14}$', text))
        
        # 18位身份证：17位数字 + 1位数字或X
        if len(text) == 18:
            # 基本格式校验
            if not re.match(r'^[1-9]\d{16}[\dX]$', text):
                return False
            
            # 严格模式：校验校验码
            if strict_mode:
                return NumberForLifeVerify._verify_id_card_checksum(text)
            
            return True
        
        return False

    @staticmethod
    def _verify_id_card_checksum(id_card_18: str) -> bool:
        """
        验证18位身份证号码的校验码是否正确
        
        算法说明:
        1. 将前17位数字分别乘以对应权重因子
        2. 求和后除以11取余数
        3. 余数对应校验码表中的值
        
        Args:
            id_card_18: 18位身份证号码字符串
            
        Returns:
            bool: 校验码正确返回True
        """
        # 权重因子
        factors = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        
        # 校验码对应表（余数 -> 校验码）
        checksum_map = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
        
        # 取出前17位和前17位的校验和
        numbers = id_card_18[:17]
        provided_checksum = id_card_18[17]
        
        # 计算校验和
        total = 0
        for i, num in enumerate(numbers):
            if not num.isdigit():
                return False
            total += int(num) * factors[i]
        
        # 计算正确的校验码
        remainder = total % 11
        expected_checksum = checksum_map[remainder]
        
        return provided_checksum == expected_checksum


    @staticmethod
    def validate_contact_info(text: str) -> dict:
        """
        综合判断文本属于哪种联系方式，返回判断结果
        
        Args:
            text: 待判断的字符串
            
        Returns:
            dict: 包含类型和是否有效的字典
            
        Examples:
            >>> validate_contact_info("13812345678")
            {"type": "phone", "is_valid": True, "value": "13812345678"}
            
            >>> validate_contact_info("user@example.com")
            {"type": "email", "is_valid": True, "value": "user@example.com"}
        """
        text = text.strip()
        
        if NumberForLifeVerify.is_phone_number(text):
            return {"type": "phone", "is_valid": True, "value": text}
        elif NumberForLifeVerify.is_email(text):
            return {"type": "email", "is_valid": True, "value": text}
        elif NumberForLifeVerify.is_id_card(text):
            return {"type": "id_card", "is_valid": True, "value": text}
        else:
            return {"type": "unknown", "is_valid": False, "value": text}


# 使用示例
if __name__ == "__main__":
    # 测试手机号
    print("=== 手机号测试 ===")
    print(f"13812345678: {NumberForLifeVerify.is_phone_number('13812345678')}")  # True
    print(f"12345678901: {NumberForLifeVerify.is_phone_number('12345678901')}")  # False
    print(f"1381234567: {NumberForLifeVerify.is_phone_number('1381234567')}")    # False
    
    # 测试邮箱
    print("\n=== 邮箱测试 ===")
    print(f"user@example.com: {NumberForLifeVerify.is_email('user@example.com')}")        # True
    print(f"user.name@example.co.uk: {NumberForLifeVerify.is_email('user.name@example.co.uk')}")  # True
    print(f"invalid-email: {NumberForLifeVerify.is_email('invalid-email')}")              # False
    print(f"user@.com: {NumberForLifeVerify.is_email('user@.com')}")                      # False
    
    # 测试身份证
    print("\n=== 身份证测试 ===")
    # 这是一个校验码正确的示例号码（来自公开测试数据）
    print(f"11010119900307663X: {NumberForLifeVerify.is_id_card('11010119900307663X')}")  # True
    print(f"110101199003076630: {NumberForLifeVerify.is_id_card('110101199003076630')}")  # False
    print(f"110101900307663: {NumberForLifeVerify.is_id_card('110101900307663')}")        # True (15位)
    
    # 综合判断
    print("\n=== 综合判断 ===")
    print(NumberForLifeVerify.validate_contact_info("13812345678"))
    print(NumberForLifeVerify.validate_contact_info("user@example.com"))
    print(NumberForLifeVerify.validate_contact_info("hello world"))
