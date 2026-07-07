class Solution(object):
    def maxSubArray(self, nums):
        """
        :type nums: List[int]
        :rtype: int
        """
        curr_val=[0]
        max_val=[0]
        n=len(nums)
        for i in range(1,n):
            curr_val=max(nums[i],curr_val+nums[i])
            max_val=max(max_val,curr_val)
        return max_val 